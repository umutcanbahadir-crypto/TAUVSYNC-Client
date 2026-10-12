"""TAUV Team Workspace — standalone dark-mode project launcher for KiCad 10.

The same window is launched from Windows or through KiCad's IPC plugin.
Only the sync engine and the HTTPS API manipulate working project copies.
All network and filesystem operations run off the UI thread.
"""
from __future__ import annotations

import io
from pathlib import Path
import queue
import threading
from tkinter import filedialog, messagebox
from typing import Any, Callable

import customtkinter as ctk
from PIL import Image

from .api import PrismAPI, APIError
from .app import DEFAULT_SERVER, LOGO_PATH, load_preferences, open_kicad, save_preferences, find_project_file
from .credentials import load_login, store_login, forget_login, CredentialStoreUnavailable
from .instance import AlreadyRunning, single_instance, focus_existing_window
from .project_templates import create_cloud_project
from .sync import SyncEngine, editor_running, unavailable_cloud_status

BG = "#08090b"
CARD = "#0c0d10"
EDGE = "#292c32"
SUBTLE = "#a3a7b1"
WHITE = "#f5f5f7"
HOVER = "#1a1d22"
BLUE = "#5488d8"
APP_TITLE = "TAUV — Team Workspace"


def _logo(size: int) -> ctk.CTkImage | None:
    if not LOGO_PATH.is_file():
        return None
    try:
        src = Image.open(LOGO_PATH).convert("RGBA")
        # Make the navy backdrop of the original supplied icon transparent
        # while retaining its white anti-aliased geometry.
        src = src.resize((size * 2, size * 2), Image.Resampling.LANCZOS)
        alpha = Image.new("L", src.size)
        alpha.putdata([max(0, min(255, round((max(r, g, b) - 15) * 255 / 235)))
                       for r, g, b, _ in src.getdata()])
        white = Image.new("RGBA", src.size, (255, 255, 255, 255))
        white.putalpha(alpha)
        return ctk.CTkImage(light_image=white, dark_image=white, size=(size, size))
    except (OSError, ValueError):
        return None


class Workspace(ctk.CTk):
    def __init__(self, current_project: str | None = None):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1040x780")
        self.minsize(780, 595)
        self.configure(fg_color=BG)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.launch_project = Path(current_project) if current_project else None
        self.settings = load_preferences()
        self.api: PrismAPI | None = None
        self.engine: SyncEngine | None = None
        self.user: dict = {}
        self.projects: list[dict] = []
        self.selected_id: str | None = None
        self.paused = False
        self.connected = False
        self.busy = False
        self.events: queue.Queue = queue.Queue()
        self.stop = threading.Event()
        self.io_lock = threading.RLock()
        self.preview_image = None
        self._logo_image = _logo(36)
        self._make_widgets()
        self.after(120, self._consume)
        previous_email = self.settings.get("email", "")
        previous_url = self.settings.get("url") or DEFAULT_SERVER
        if self.settings.get("remember") and previous_email:
            secret = load_login(previous_url, previous_email)
            if secret:
                self.after(250, lambda: self._login(secret))

    def _text(self, parent, value, size=14, weight="normal", color=WHITE, **kwargs):
        return ctk.CTkLabel(
            parent, text=value, font=ctk.CTkFont(family="Segoe UI", size=size, weight=weight),
            text_color=color, **kwargs,
        )

    def _make_widgets(self):
        shell = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        shell.pack(fill="both", expand=True, padx=27, pady=24)
        self.shell = shell

        header = ctk.CTkFrame(shell, fg_color="transparent")
        header.pack(fill="x", pady=(2, 19))
        if self._logo_image:
            ctk.CTkLabel(header, text="", image=self._logo_image).pack(side="left", padx=(2, 10))
        self._text(header, APP_TITLE, size=21, weight="bold").pack(side="left")
        self.connection = self._text(header, "Offline", 12, color=SUBTLE)
        self.connection.pack(side="right", padx=8)

        self.login_panel = ctk.CTkFrame(shell, fg_color=CARD, border_width=1, border_color=EDGE, corner_radius=12)
        self.login_panel.pack(fill="x", pady=(35, 0), ipady=20)
        self._text(self.login_panel, "Sign in to TAUV", 22, "bold").pack(anchor="w", padx=28, pady=(6, 3))
        self._text(self.login_panel, "Use your existing team account. No Git or SSH required.", 13, color=SUBTLE).pack(anchor="w", padx=28, pady=(0, 16))
        self.server = ctk.CTkEntry(self.login_panel, height=40, fg_color=BG, border_color=EDGE)
        self.server.pack(fill="x", padx=28, pady=(0, 10))
        self.server.insert(0, self.settings.get("url") or DEFAULT_SERVER)
        self.email = ctk.CTkEntry(self.login_panel, height=40, placeholder_text="Email", fg_color=BG, border_color=EDGE)
        self.email.pack(fill="x", padx=28, pady=(0, 10))
        self.email.insert(0, self.settings.get("email", ""))
        self.password = ctk.CTkEntry(self.login_panel, height=40, placeholder_text="Password", show="●", fg_color=BG, border_color=EDGE)
        self.password.pack(fill="x", padx=28, pady=(0, 10))
        self.password.bind("<Return>", lambda _e: self._login())
        self.workspace_field = ctk.CTkEntry(self.login_panel, height=40, fg_color=BG, border_color=EDGE)
        self.workspace_field.pack(fill="x", padx=28, pady=(0, 12))
        self.workspace_field.insert(0, self.settings.get("workspace") or str(Path.home() / "TAUVSYNC"))
        self.remember = ctk.BooleanVar(value=bool(self.settings.get("remember", False)))
        ctk.CTkCheckBox(self.login_panel, text="Remember login securely on this PC",
                        variable=self.remember, fg_color=BLUE).pack(anchor="w", padx=28, pady=(0, 12))
        ctk.CTkButton(self.login_panel, text="Log in", height=41, command=self._login,
                      fg_color=BLUE, hover_color="#3e6cb2").pack(fill="x", padx=28, pady=(0, 4))

        self.main = ctk.CTkFrame(shell, fg_color=CARD, border_width=1, border_color=EDGE, corner_radius=12)
        # Remains hidden until authentication succeeds.
        self.topbar = ctk.CTkFrame(self.main, fg_color="transparent")
        self.topbar.pack(fill="x", padx=18, pady=(17, 10))
        self._text(self.topbar, "Shared projects", 19, "bold").pack(side="left")
        self.count = self._text(self.topbar, "0 projects", 12, "bold", color=WHITE)
        self.count.pack(side="right", padx=(12, 0))
        self._text(self.topbar, "ACTIVE", 10, "bold", color=SUBTLE).pack(side="right")

        self.search = ctk.StringVar()
        self.search.trace_add("write", lambda *_: self._draw_projects())
        search_row = ctk.CTkFrame(self.main, fg_color="transparent")
        search_row.pack(fill="x", padx=18, pady=(0, 10))
        ctk.CTkEntry(
            search_row, textvariable=self.search, height=39,
            placeholder_text="⌕  Search projects...", fg_color=BG, border_color=EDGE,
        ).pack(side="left", fill="x", expand=True)
        self.filter_removed = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(search_row, text="Removed", variable=self.filter_removed,
                        command=self._draw_projects, width=93, fg_color=BLUE).pack(side="right", padx=(16, 0))

        self.list_area = ctk.CTkScrollableFrame(self.main, fg_color="transparent", height=236)
        self.list_area.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        self.rows: list[ctk.CTkFrame] = []

        self.detail = ctk.CTkFrame(self.main, fg_color=BG, corner_radius=9, border_width=1, border_color=EDGE)
        self.detail.pack(fill="x", padx=18, pady=(0, 12))
        self.preview = ctk.CTkLabel(self.detail, text="Select a project to preview", width=120, height=112,
                                    text_color=SUBTLE)
        self.preview.pack(side="left", padx=12, pady=12)
        self.project_text = ctk.CTkFrame(self.detail, fg_color="transparent")
        self.project_text.pack(side="left", fill="x", expand=True, padx=(8, 12))
        self.project_name = self._text(self.project_text, "No project selected", 16, "bold", anchor="w")
        self.project_name.pack(fill="x", pady=(5, 4))
        self.project_info = self._text(self.project_text, "Select an item above to see details.", 12, color=SUBTLE, anchor="w", justify="left")
        self.project_info.pack(fill="x")

        buttons = ctk.CTkFrame(self.main, fg_color="transparent")
        buttons.pack(fill="x", padx=18, pady=(0, 16))
        buttons.grid_columnconfigure((0, 1), weight=1)
        self.new_button = ctk.CTkButton(
            buttons, text="⊕   New Project", height=53, fg_color="#121419",
            hover_color=HOVER, border_width=1, border_color=EDGE, command=self._new_project,
            font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
        )
        self.new_button.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.open_button = ctk.CTkButton(
            buttons, text="▢   Open in KiCad", height=53, fg_color="#121419",
            hover_color=HOVER, border_width=1, border_color=EDGE, command=self._open_selected,
            font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
        )
        self.open_button.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        small = ctk.CTkFrame(self.main, fg_color="transparent")
        small.pack(fill="x", padx=18, pady=(0, 16))
        for text, action in (
            ("Import Existing", self._import_existing), ("History", self._history),
            ("Sync now", self._sync_now), ("Pause sync", self._toggle_pause),
            ("Sign out", self._logout),
        ):
            ctk.CTkButton(small, text=text, width=112, height=30,
                          fg_color="#15171b", hover_color=HOVER,
                          command=action).pack(side="left", padx=(0, 7))
        self.footer = ctk.CTkFrame(shell, fg_color="transparent")
        self.footer.pack(fill="x", pady=(12, 0))
        self.status = ctk.StringVar(value="Log in to browse team projects.")
        self._text(self.footer, "", 12, color=SUBTLE, textvariable=self.status, anchor="w").pack(side="left", fill="x", expand=True)

    def _task(self, label: str, task: Callable, done: Callable[[Any], None]):
        if self.busy:
            self._set_status("An operation is still running. Please wait.")
            return
        self.busy = True
        self._set_status(label)
        def worker():
            try:
                with self.io_lock:
                    value = task()
                self.events.put(("done", done, value))
            except Exception as error:
                self.events.put(("error", error))
        threading.Thread(target=worker, daemon=True).start()

    def _consume(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "done":
                    self.busy = False
                    try:
                        event[1](event[2])
                    except Exception as error:
                        self._set_status(str(error))
                        messagebox.showerror("TAUV", str(error), parent=self)
                elif event[0] == "error":
                    self.busy = False
                    self._set_status("Operation failed: " + str(event[1]))
                    messagebox.showerror("TAUV", str(event[1]), parent=self)
                elif event[0] == "poll":
                    self.projects = event[1]
                    self._draw_projects()
                elif event[0] == "poll_error":
                    self.connection.configure(text="Offline")
                    self._set_status("Connection lost; saved local work remains untouched.")
                elif event[0] == "thumbnail":
                    if self.selected_id == event[1]:
                        self._display_thumbnail(event[2])
        except queue.Empty:
            pass
        if not self.stop.is_set():
            self.after(180, self._consume)

    def _set_status(self, message: str):
        self.status.set(message[:400])

    def _login(self, remembered: str | None = None):
        url = self.server.get().strip()
        email = self.email.get().strip()
        password = remembered if remembered is not None else self.password.get()
        folder = self.workspace_field.get().strip()
        remember = bool(self.remember.get())
        if not email or not password or not folder:
            messagebox.showwarning("TAUV", "Email, password and workspace are required.", parent=self)
            return
        self.password.delete(0, "end")
        def work():
            api = PrismAPI(url)
            user = api.login(email, password)
            engine = SyncEngine(api, Path(folder))
            projects = api.projects()
            # Persist settings only after successful login and server discovery.
            save_preferences(url, folder, email, remember)
            if remember:
                store_login(url, email, password)
            else:
                forget_login()
            return api, user, engine, projects
        def complete(result):
            self.api, self.user, self.engine, self.projects = result
            self.connected = True
            self.connection.configure(text=email + "  •  Connected")
            self.login_panel.pack_forget()
            self.main.pack(fill="both", expand=True)
            self._draw_projects()
            self._set_status("Connected. TAUV syncs while this window is open or minimized.")
            threading.Thread(target=self._poll_loop, daemon=True).start()
        self._task("Signing in to TAUV…", work, complete)

    def _poll_loop(self):
        while not self.stop.wait(5):
            if not self.connected or self.paused or not self.api or not self.engine:
                continue
            try:
                with self.io_lock:
                    remote = self.api.projects()
                    local = self.engine.local_projects()
                    editors_open = editor_running()
                    for project in remote:
                        pid = project["id"]
                        if pid in local:
                            self.engine.poll(
                                pid, project, editors_open=editors_open,
                                allow_publish=self.user.get("role") in ("designer", "admin"),
                            )
                self.events.put(("poll", remote))
            except Exception:
                self.events.put(("poll_error", None))

    def _draw_projects(self):
        if not self.connected:
            return
        for row in self.rows:
            row.destroy()
        self.rows.clear()
        search = self.search.get().strip().casefold()
        show_removed = self.filter_removed.get()
        filtered = [
            p for p in self.projects
            if (bool(unavailable_cloud_status(p)) == show_removed)
            and (not search or search in p.get("name", "").casefold())
        ]
        self.count.configure(text=f"{len(filtered)} project{'s' if len(filtered) != 1 else ''}")
        for project in filtered:
            pid = project["id"]
            selected = self.selected_id == pid
            row = ctk.CTkFrame(self.list_area, fg_color="#1c2028" if selected else "transparent",
                               corner_radius=8, height=42)
            row.pack(fill="x", pady=2)
            name = self._text(row, "▱  " + project["name"], 15, "bold" if selected else "normal")
            name.pack(side="left", padx=12, pady=10)
            self._text(row, "r" + str(project.get("head_revision", "?")), 12, color=SUBTLE).pack(side="right", padx=14)
            for item in (row, name):
                item.bind("<Button-1>", lambda _e, p=pid: self._select(p))
                item.bind("<Double-1>", lambda _e, p=pid: (self._select(p), self._open_selected()))
            self.rows.append(row)
        if not filtered:
            empty = ctk.CTkFrame(self.list_area, fg_color="transparent")
            empty.pack(fill="x", pady=32)
            self._text(empty, "No projects found", 13, color=SUBTLE).pack()
            self.rows.append(empty)
        self.new_button.configure(state="normal" if self.user.get("role") in ("designer", "admin") else "disabled")
        self.open_button.configure(state="normal" if self._selected() else "disabled")

    def _selected(self) -> dict | None:
        return next((p for p in self.projects if p["id"] == self.selected_id), None)

    def _select(self, pid: str):
        self.selected_id = pid
        project = self._selected()
        self._draw_projects()
        if not project:
            return
        info = "Cloud r" + str(project.get("head_revision", "?"))
        local = self.engine.local_projects() if self.engine else {}
        info += "  •  " + ("Downloaded" if pid in local else "Cloud only")
        if self.engine and pid in self.engine.status:
            info += "\n" + self.engine.status[pid]
        if unavailable_cloud_status(project):
            info += "\nRemoved from the shared workspace; local files are preserved."
        self.project_name.configure(text=project["name"])
        self.project_info.configure(text=info)
        self.preview.configure(text="Loading preview...", image=None)
        self.preview_image = None
        prism_id = project.get("prism_project_id")
        if prism_id and not unavailable_cloud_status(project):
            threading.Thread(target=self._load_preview, args=(pid, prism_id), daemon=True).start()
        else:
            self.preview.configure(text="No preview available")

    def _load_preview(self, pid: str, prism_id: str):
        if not self.api:
            return
        try:
            with self.io_lock:
                data = self.api.thumbnail(prism_id)
            self.events.put(("thumbnail", pid, data))
        except Exception:
            self.events.put(("thumbnail", pid, None))

    def _display_thumbnail(self, data: bytes | None):
        if not data:
            self.preview.configure(text="No preview yet", image=None)
            return
        try:
            with Image.open(io.BytesIO(data)) as img:
                img.thumbnail((188, 118), Image.Resampling.LANCZOS)
                bitmap = img.convert("RGBA").copy()
            self.preview_image = ctk.CTkImage(light_image=bitmap, dark_image=bitmap, size=bitmap.size)
            self.preview.configure(image=self.preview_image, text="")
        except (OSError, ValueError):
            self.preview.configure(text="Preview unavailable", image=None)

    def _refresh(self):
        if not self.api:
            return
        self._task("Refreshing projects…", self.api.projects, self._receive_projects)

    def _receive_projects(self, projects):
        self.projects = projects
        self._draw_projects()
        self._set_status("Cloud projects refreshed.")

    def _sync_now(self):
        if not self.api or not self.engine:
            return
        def work():
            projects = self.api.projects()
            local = self.engine.local_projects()
            editors_open = editor_running()
            for project in projects:
                if project["id"] in local:
                    self.engine.poll(
                        project["id"], project, editors_open=editors_open,
                        allow_publish=self.user.get("role") in ("designer", "admin"),
                    )
            return projects
        def completed(projects):
            self.projects = projects
            self._draw_projects()
            self._set_status("Manual synchronization completed; see each project's status.")
            if self.selected_id:
                self._select(self.selected_id)
        self._task("Checking for local and cloud changes…", work, completed)

    def _toggle_pause(self):
        self.paused = not self.paused
        self._set_status("Synchronization paused. Projects stay on disk." if self.paused else "Synchronization resumed.")

    def _new_project(self):
        if not self.engine or not self.api:
            return
        if self.user.get("role") not in ("designer", "admin"):
            messagebox.showwarning("TAUV", "Designer or Admin permission required.", parent=self)
            return
        dialog = ctk.CTkToplevel(self)
        dialog.title("Create KiCad project")
        dialog.geometry("420x320")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()
        self._text(dialog, "New team project", 20, "bold").pack(anchor="w", padx=24, pady=(24, 12))
        name = ctk.CTkEntry(dialog, placeholder_text="Project name", height=41)
        name.pack(fill="x", padx=24, pady=(0, 12))
        kind = ctk.StringVar(value="Schematic + PCB")
        ctk.CTkOptionMenu(dialog, variable=kind,
                          values=["Schematic + PCB", "Schematic only", "PCB only"],
                          height=38).pack(fill="x", padx=24)
        open_after = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(dialog, text="Open in KiCad after creation",
                        variable=open_after).pack(anchor="w", padx=24, pady=(16, 10))
        def create():
            title = name.get().strip()
            key = {"Schematic + PCB": "both", "Schematic only": "schematic", "PCB only": "pcb"}[kind.get()]
            should_open = open_after.get()
            dialog.grab_release()
            dialog.destroy()
            def work():
                return create_cloud_project(self.api, self.engine, title, key)
            def done(result):
                project, path = result
                self.projects = [p for p in self.projects if p["id"] != project["id"]] + [project]
                self._select(project["id"])
                self._set_status("Created " + project["name"] + " as cloud revision r1.")
                if should_open:
                    open_kicad(path)
            self._task("Creating KiCad project and first cloud revision…", work, done)
        ctk.CTkButton(dialog, text="Create project", height=42, command=create).pack(fill="x", padx=24, pady=(12, 0))
        name.focus_set()

    def _open_selected(self):
        project = self._selected()
        if not project or not self.engine:
            self._set_status("Select a project first.")
            return
        pid = project["id"]
        if unavailable_cloud_status(project):
            existing = self.engine.local_projects().get(pid)
            if not existing:
                messagebox.showwarning("TAUV", "Project was removed and no local copy exists.", parent=self)
                return
            path = self.engine.folder(pid) / existing["project_file"]
            open_kicad(path)
            return
        def work():
            # Checking out a known project never overwrites an existing local copy.
            return self.engine.checkout(project)
        def done(path):
            open_kicad(path)
            self._set_status("Opened managed project: " + project["name"])
            self._select(pid)
        self._task("Preparing managed KiCad project…", work, done)

    def _import_existing(self):
        if not self.engine or not self.api:
            return
        if self.user.get("role") not in ("designer", "admin"):
            messagebox.showwarning("TAUV", "Designer or Admin permission required.", parent=self)
            return
        chosen = filedialog.askopenfilename(
            parent=self, title="Import an existing KiCad project",
            filetypes=[("KiCad projects", "*.kicad_pro")],
        )
        if not chosen:
            return
        project_file = find_project_file(Path(chosen))
        if not project_file:
            messagebox.showerror("TAUV", "Select a valid .kicad_pro file.", parent=self)
            return
        from tkinter import simpledialog
        name = simpledialog.askstring("Import project", "Cloud project name:",
                                      initialvalue=project_file.stem, parent=self)
        if not name:
            return
        if not messagebox.askyesno(
            "Import existing project",
            "A separate managed copy will be created. Your original project files "
            "are not modified. Continue editing the managed copy after import.",
            parent=self,
        ):
            return
        def done(result):
            project, path = result
            self.projects = [p for p in self.projects if p["id"] != project["id"]] + [project]
            self._select(project["id"])
            self._set_status("Imported. Your original files are unchanged.")
            if messagebox.askyesno("TAUV", "Open the synchronized managed copy now?", parent=self):
                open_kicad(path)
        self._task("Importing existing project…",
                   lambda: self.engine.upload_local_project(project_file, name), done)

    def _history(self):
        project = self._selected()
        if not self.api or not project:
            self._set_status("Select a project to view its version history.")
            return
        self._task("Loading revision history…",
                   lambda: self.api.revisions(project["id"]),
                   lambda revisions: self._history_window(project, revisions))

    def _history_window(self, project: dict, revisions: list[dict]):
        win = ctk.CTkToplevel(self)
        win.title("TAUV — " + project["name"] + " history")
        win.geometry("640x480")
        win.transient(self)
        self._text(win, "Version history: " + project["name"], 19, "bold").pack(padx=20, pady=(18, 10))
        scroll = ctk.CTkScrollableFrame(win, fg_color=CARD)
        scroll.pack(fill="both", expand=True, padx=20)
        selected_rev = ctk.IntVar(value=int(revisions[0]["number"]) if revisions else 0)
        for revision in revisions:
            number = int(revision["number"])
            label = (f"r{number}    {revision.get('status','')}   "
                     f"{revision.get('author','')}  {revision.get('created_at','')}")
            ctk.CTkRadioButton(scroll, text=label, variable=selected_rev, value=number,
                               fg_color=BLUE).pack(anchor="w", pady=7, padx=10)
        actions = ctk.CTkFrame(win, fg_color="transparent")
        actions.pack(fill="x", padx=20, pady=15)
        def download():
            rev = selected_rev.get()
            if not rev:
                return
            target = filedialog.asksaveasfilename(
                parent=win, initialfile=f"{project['name']}-r{rev}.zip",
                defaultextension=".zip", filetypes=[("ZIP archive", "*.zip")])
            if target:
                self._task("Downloading r" + str(rev) + "…",
                           lambda: self.api.download(project["id"], rev, Path(target)),
                           lambda _unused: self._set_status(f"Downloaded r{rev} to {target}"))
        def restore():
            rev = selected_rev.get()
            if (not rev or self.user.get("role") not in ("designer", "admin")
                    or unavailable_cloud_status(project)):
                return
            if not messagebox.askyesno(
                "Restore revision", f"Publish r{rev} as a new HEAD revision?\n"
                "All historical versions are preserved.", parent=win):
                return
            self._task("Restoring r" + str(rev) + "…",
                       lambda: self.api.restore(project["id"], rev),
                       lambda _result: (self._set_status("Revision restored; refresh projects."), self._refresh()))
        ctk.CTkButton(actions, text="Download ZIP", command=download).pack(side="left", padx=(0, 8))
        can_restore = self.user.get("role") in ("designer", "admin") and not unavailable_cloud_status(project)
        ctk.CTkButton(actions, text="Restore as latest", command=restore,
                      state="normal" if can_restore else "disabled").pack(side="left")
        ctk.CTkButton(actions, text="Close", command=win.destroy).pack(side="right")

    def _logout(self):
        self.stop.set()
        if self.api:
            try:
                self.api.cookies.clear()
            except Exception:
                pass
        forget_login()
        self.connected = False
        self.destroy()  # restart the app to sign into a different account

    def _on_close(self):
        if self.connected and not messagebox.askyesno(
            "Exit TAUV", "Exit TAUV and stop automatic synchronization?\n"
            "Minimize instead to keep syncing.", parent=self):
            return
        self.stop.set()
        self.destroy()


def run_launcher(current_project: str | None = None) -> None:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    from tkinter import messagebox as tk_msg
    try:
        with single_instance():
            app = Workspace(current_project=current_project)
            app.mainloop()
    except AlreadyRunning:
        if not focus_existing_window(APP_TITLE):
            tk_msg.showinfo("TAUV", "The TAUV workspace is already running.")
