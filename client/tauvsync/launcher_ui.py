"""TAUV Team Workspace — standalone dark-mode project launcher for KiCad 10.

The same window is launched from Windows or through KiCad's IPC plugin.
Only the sync engine and the HTTPS API manipulate working project copies.
All network and filesystem operations run off the UI thread.
"""
from __future__ import annotations

import io
import sys
import tkinter as tk
from pathlib import Path
import queue
import threading
import time
import webbrowser
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
from .workspace_data import next_available_name, reconcile_projects, latest_authors, synced_status_label
from .update_check import APP_VERSION, check_for_update

BG = "#08090b"
CARD = "#0c0d10"
EDGE = "#292c32"
SUBTLE = "#a3a7b1"
WHITE = "#f5f5f7"
HOVER = "#1a1d22"
BLUE = "#5488d8"
APP_TITLE = "TAUV — Team Workspace"


def _logo(size: int) -> ctk.CTkImage | None:
    """Display the supplied logo's true alpha channel without RGB keying."""
    if not LOGO_PATH.is_file():
        return None
    try:
        with Image.open(LOGO_PATH) as asset:
            src = asset.convert("RGBA")
        return ctk.CTkImage(light_image=src, dark_image=src, size=(size, size))
    except (OSError, ValueError):
        return None


class Workspace(ctk.CTk):
    def __init__(self, current_project: str | None = None):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1040x780")
        self.minsize(780, 595)
        self.configure(fg_color=BG)
        self._window_icon = None
        try:
            if LOGO_PATH.is_file():
                self._window_icon = tk.PhotoImage(file=str(LOGO_PATH))
                self.iconphoto(True, self._window_icon)
            if sys.platform == "win32":
                ico = LOGO_PATH.with_name("tauv_app.ico")
                if ico.is_file():
                    self.iconbitmap(str(ico))
        except (OSError, tk.TclError):
            pass  # Icon errors must never prevent application startup.
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.launch_project = Path(current_project) if current_project else None
        self.settings = load_preferences()
        self.api: PrismAPI | None = None
        self.engine: SyncEngine | None = None
        self.user: dict = {}
        self.projects: list[dict] = []
        self.authors: dict[tuple[str, int], str] = {}
        self.thumbnail_cache: dict[tuple[str, int], bytes | None] = {}
        self.thumbnail_images: dict[tuple[str, int, str], ctk.CTkImage] = {}
        self.thumbnail_inflight: set[tuple[str, int]] = set()
        self.thumbnail_attempts: dict[tuple[str, int], float] = {}
        self.thumbnail_labels: dict[str, ctk.CTkLabel] = {}
        self._render_signature = None
        self.selected_id: str | None = None
        self.paused = False
        self.connected = False
        self.busy = False
        self.events: queue.Queue = queue.Queue()
        self.stop = threading.Event()
        self.io_lock = threading.RLock()
        self._lease_renew_at: dict[str, float] = {}
        self.preview_image = None
        self._logo_image = _logo(36)
        self._make_widgets()
        self.after(120, self._consume)
        self.after(400, self._check_updates_on_launch)
        previous_email = self.settings.get("email", "")
        previous_url = self.settings.get("url") or DEFAULT_SERVER
        if self.settings.get("remember") and previous_email:
            secret = load_login(previous_url, previous_email)
            if secret:
                self.after(250, lambda: self._login(secret))

    def _check_updates_on_launch(self):
        """Check once per launch without delaying login or synchronization."""
        def worker():
            update = check_for_update()
            if update and not self.stop.is_set():
                self.events.put(("update_available", update))
        threading.Thread(target=worker, daemon=True).start()

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
        self.sync_badge = ctk.CTkLabel(
            self.project_text,
            text="",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color="#f0fff4",
            fg_color="#17683f",
            corner_radius=7,
            width=110,
            height=26,
        )
        self.sync_badge.pack_forget()

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
            ("Release lock", self._release_selected_lock), ("Admin unlock", self._admin_force_unlock),
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
                elif event[0] == "update_available":
                    update = event[1]
                    if messagebox.askyesno(
                        "TAUVSYNC — Update available",
                        f"TAUVSYNC {update.version} is available.\n"
                        f"Installed version: {APP_VERSION}\n\n"
                        "Open the official GitHub release page to download?\n"
                        "TAUVSYNC will not replace its executable or change your projects.",
                        parent=self,
                    ):
                        webbrowser.open(update.release_url)
                elif event[0] == "poll":
                    self.projects, self.authors = event[1], event[2]
                    self.connection.configure(text="Connected")
                    self._draw_projects()
                    if self.selected_id:
                        self._update_details()
                elif event[0] == "poll_error":
                    self.connection.configure(text="Offline")
                    self._set_status("Connection lost; saved local work remains untouched.")
                elif event[0] == "lock_lost":
                    self._set_status("Editing lock lost: " + str(event[1]) +
                                     ". Publishing paused until reopened. " + str(event[2]))
                elif event[0] == "thumbnail":
                    key, data = event[1], event[2]
                    self.thumbnail_inflight.discard(key)
                    self.thumbnail_cache[key] = data
                    self._draw_projects(force=True)
                    if self.selected_id == key[0]:
                        selected = self._selected()
                        if selected and int(selected.get("head_revision") or 0) == key[1]:
                            self._display_thumbnail(data)
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
            projects = reconcile_projects(api.projects(), engine.local_projects())
            authors = latest_authors(api, projects, {})
            # Persist settings only after successful login and server discovery.
            save_preferences(url, folder, email, remember)
            if remember:
                store_login(url, email, password)
            else:
                forget_login()
            return api, user, engine, projects, authors
        def complete(result):
            self.api, self.user, self.engine, self.projects, self.authors = result
            self.connected = True
            self.connection.configure(text=email + "  •  Connected")
            self.login_panel.pack_forget()
            self.main.pack(fill="both", expand=True)
            self._draw_projects()
            self._set_status("Connected. TAUV syncs while this window is open or minimized.")
            threading.Thread(target=self._poll_loop, daemon=True).start()
        self._task("Signing in to TAUV…", work, complete)

    def _get_project_snapshot(self):
        """Refresh metadata even while local synchronization is paused."""
        remote = reconcile_projects(self.api.projects(), self.engine.local_projects())
        authors = latest_authors(self.api, remote, self.authors)
        return remote, authors

    def _poll_loop(self):
        while not self.stop.wait(5):
            if not self.connected or not self.api or not self.engine:
                continue
            try:
                with self.io_lock:
                    remote, authors = self._get_project_snapshot()
                    for pid in tuple(self.api.edit_tokens):
                        if time.monotonic() - self._lease_renew_at.get(pid, 0) >= 30:
                            try:
                                self.api.renew_edit_lock(pid)
                                self._lease_renew_at[pid] = time.monotonic()
                            except APIError as error:
                                self.api.edit_tokens.pop(pid, None)
                                self._lease_renew_at.pop(pid, None)
                                self.events.put(("lock_lost", pid, str(error)))
                    if not self.paused:
                        local = self.engine.local_projects()
                        managed = [
                            p for p in remote if p["id"] in local
                            and not unavailable_cloud_status(p)
                        ]
                        editors_open = editor_running() if managed else False
                        for project in remote:
                            if project["id"] in local:
                                self.engine.poll(
                                    project["id"], project, editors_open=editors_open,
                                    allow_publish=(self.user.get("role") in ("designer", "admin")
                                                    and self.api.has_edit_lock(project["id"])),
                                )
                self.events.put(("poll", remote, authors))
            except Exception:
                self.events.put(("poll_error", None))

    def _thumbnail_key(self, project: dict) -> tuple[str, int]:
        return project["id"], int(project.get("head_revision") or 0)

    def _thumbnail_image(self, project: dict, kind: str) -> ctk.CTkImage | None:
        key = self._thumbnail_key(project)
        data = self.thumbnail_cache.get(key)
        if not data:
            return None
        image_key = key + (kind,)
        if image_key in self.thumbnail_images:
            return self.thumbnail_images[image_key]
        try:
            with Image.open(io.BytesIO(data)) as img:
                img.thumbnail((180, 120) if kind == "detail" else (88, 56),
                              Image.Resampling.LANCZOS)
                bitmap = img.convert("RGBA").copy()
            dims = bitmap.size
            icon = ctk.CTkImage(light_image=bitmap, dark_image=bitmap, size=dims)
            self.thumbnail_images[image_key] = icon
            return icon
        except (OSError, ValueError):
            return None

    def _request_thumbnail(self, project: dict):
        if not self.api or unavailable_cloud_status(project):
            return
        prism_id = project.get("prism_project_id")
        if not prism_id:
            return
        key = self._thumbnail_key(project)
        if key in self.thumbnail_inflight:
            return
        # Missing thumbnails are retried after Prism's asynchronous rendering.
        last = self.thumbnail_attempts.get(key, 0)
        if key in self.thumbnail_cache and (
                self.thumbnail_cache[key] is not None or time.monotonic() - last < 60):
            return
        self.thumbnail_attempts[key] = time.monotonic()
        self.thumbnail_inflight.add(key)
        threading.Thread(target=self._load_preview,
                         args=(key, prism_id), daemon=True).start()

    def _draw_projects(self, force: bool = False):
        if not self.connected:
            return
        search = self.search.get().strip().casefold()
        show_removed = self.filter_removed.get()
        filtered = [
            p for p in self.projects
            if (bool(unavailable_cloud_status(p)) == show_removed)
            and (not search or search in p.get("name", "").casefold())
        ]
        signature = (
            search, show_removed, self.selected_id,
            tuple((p["id"], p.get("name"), p.get("head_revision"),
                   p.get("cloud_state"),
                   (p.get("edit_lock") or {}).get("owner"),
                   self.authors.get(self._thumbnail_key(p), p.get("owner")))
                  for p in filtered),
        )
        if signature == self._render_signature and not force:
            return
        self._render_signature = signature
        for row in self.rows:
            row.destroy()
        self.rows.clear()
        self.thumbnail_labels.clear()
        self.count.configure(text=f"{len(filtered)} project{'s' if len(filtered) != 1 else ''}")
        for project in filtered:
            pid = project["id"]
            selected = self.selected_id == pid
            row = ctk.CTkFrame(self.list_area, fg_color="#1c2028" if selected else "transparent",
                               corner_radius=8, height=60)
            row.pack(fill="x", pady=2)
            thumbnail = self._thumbnail_image(project, "row")
            preview = ctk.CTkLabel(row, text="" if thumbnail else "▱",
                                   image=thumbnail, width=85, height=54,
                                   text_color=SUBTLE)
            preview.pack(side="left", padx=(8, 6), pady=3)
            self.thumbnail_labels[pid] = preview
            name = self._text(row, project["name"], 15, "bold" if selected else "normal")
            name.pack(side="left", padx=(0, 12), pady=10)
            lease = project.get("edit_lock") or {}
            if lease.get("owner"):
                own = bool(self.api and self.api.has_edit_lock(pid))
                self._text(row, "Editing: you" if own else "Locked: " + str(lease["owner"]),
                           11, color="#73d9a0" if own else "#ffbf69").pack(side="right", padx=6)
            rev = self._text(row, "r" + str(project.get("head_revision", "?")),
                             12, color=SUBTLE)
            rev.pack(side="right", padx=(6, 14))
            author = self.authors.get(self._thumbnail_key(project)) or project.get("owner") or "Unknown author"
            author_text = self._text(row, str(author), 12, color=SUBTLE)
            author_text.pack(side="right", padx=(8, 16))
            for item in (row, name, preview, author_text, rev):
                item.bind("<Button-1>", lambda _e, p=pid: self._select(p))
                item.bind("<Double-1>", lambda _e, p=pid: (self._select(p), self._open_selected()))
            self.rows.append(row)
            self._request_thumbnail(project)
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
        self._draw_projects()
        self._update_details()

    def _update_details(self):
        project = self._selected()
        if not project:
            self.project_name.configure(text="Project removed from server")
            self.project_info.configure(text="No cloud entry. Local copies are preserved.")
            self.sync_badge.pack_forget()
            self.preview.configure(text="No preview", image=None)
            return
        pid = project["id"]
        info = "Cloud r" + str(project.get("head_revision", "?"))
        author = self.authors.get(self._thumbnail_key(project)) or project.get("owner")
        if author:
            info += "  •  Author: " + str(author)
        local = self.engine.local_projects() if self.engine else {}
        info += "  •  " + ("Downloaded" if pid in local else "Cloud only")
        lease = project.get("edit_lock") or {}
        if lease.get("owner"):
            info += ("\nEditing lock: yours" if self.api and self.api.has_edit_lock(pid)
                     else "\nLocked by " + str(lease["owner"]) +
                          "; viewing and revision downloads remain available")
        current_status = self.engine.status.get(pid) if self.engine else None
        removed = bool(unavailable_cloud_status(project))
        badge = synced_status_label(current_status) if not removed else None
        if badge:
            self.sync_badge.configure(text=badge)
            if not self.sync_badge.winfo_manager():
                self.sync_badge.pack(anchor="w", pady=(7, 4))
        else:
            self.sync_badge.pack_forget()
            if current_status:
                info += "\n" + current_status
        if removed:
            info += "\nRemoved from the shared workspace; local files are preserved."
        self.project_name.configure(text=project["name"])
        self.project_info.configure(text=info)
        icon = self._thumbnail_image(project, "detail")
        self.preview.configure(image=icon, text="" if icon else "No preview yet")
        self.preview_image = icon
        self._request_thumbnail(project)

    def _load_preview(self, key: tuple[str, int], prism_id: str):
        if not self.api:
            return
        try:
            with self.io_lock:
                data = self.api.thumbnail(prism_id)
            self.events.put(("thumbnail", key, data))
        except Exception:
            self.events.put(("thumbnail", key, None))

    def _display_thumbnail(self, data: bytes | None):
        project = self._selected()
        icon = self._thumbnail_image(project, "detail") if project else None
        self.preview_image = icon
        self.preview.configure(text="" if icon else "No preview yet", image=icon)

    def _refresh(self):
        if not self.api:
            return
        self._task("Refreshing projects…", self._get_project_snapshot,
                   self._receive_projects)

    def _receive_projects(self, snapshot):
        self.projects, self.authors = snapshot
        self._draw_projects()
        if self.selected_id:
            self._update_details()
        self._set_status("Cloud projects refreshed; removed projects moved to Removed.")

    def _sync_now(self):
        if not self.api or not self.engine:
            return
        def work():
            projects, authors = self._get_project_snapshot()
            local = self.engine.local_projects()
            active_managed = [
                p for p in projects if p["id"] in local
                and not unavailable_cloud_status(p)
            ]
            editors_open = editor_running() if active_managed else False
            for project in projects:
                if project["id"] in local:
                    self.engine.poll(
                        project["id"], project, editors_open=editors_open,
                        allow_publish=(self.user.get("role") in ("designer", "admin")
                                                    and self.api.has_edit_lock(project["id"])),
                    )
            return projects, authors
        def completed(snapshot):
            self.projects, self.authors = snapshot
            self._draw_projects()
            self._set_status("Manual synchronization completed; see each project's status.")
            if self.selected_id:
                self._update_details()
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
                fresh = self.api.projects()
                unique_name = next_available_name(title, fresh)
                return create_cloud_project(self.api, self.engine, unique_name, key)
            def done(result):
                project, path = result
                self.projects = [p for p in self.projects if p["id"] != project["id"]] + [project]
                self.authors[self._thumbnail_key(project)] = str(project.get("owner") or "")
                self._select(project["id"])
                self._set_status("Created " + project["name"] + " as cloud revision r1.")
                if should_open:
                    self._task("Acquiring edit lock…",
                               lambda: self.api.acquire_edit_lock(project["id"]),
                               lambda _lease: (self._lease_renew_at.__setitem__(
                                   project["id"], time.monotonic()), open_kicad(path),
                                   self._refresh()))
            self._task("Creating KiCad project and first cloud revision…", work, done)
        ctk.CTkButton(dialog, text="Create project", height=42, command=create).pack(fill="x", padx=24, pady=(12, 0))
        name.focus_set()

    def _open_selected(self):
        project = self._selected()
        if not project or not self.engine or not self.api:
            self._set_status("Select a project first.")
            return
        pid = project["id"]
        if unavailable_cloud_status(project):
            existing = self.engine.local_projects().get(pid)
            if not existing:
                messagebox.showwarning("TAUV", "Project removed; no local checkout.", parent=self)
                return
            open_kicad(self.engine.folder(pid) / existing["project_file"])
            return
        if self.user.get("role") not in ("designer", "admin"):
            messagebox.showinfo(
                "TAUV — Viewer",
                "Only a Designer or Admin may open a shared project for editing. "
                "Use History to download a snapshot.", parent=self)
            return
        lease = project.get("edit_lock") or {}
        if lease and not self.api.has_edit_lock(pid):
            messagebox.showinfo(
                "TAUV — Project locked",
                "This project is currently being edited by " + str(lease["owner"]) +
                ". Another user cannot open it for editing or publish changes. "
                "Use History to download a snapshot.", parent=self)
            return

        def work():
            held = self.api.has_edit_lock(pid)
            if held:
                self.api.renew_edit_lock(pid)
            else:
                self.api.acquire_edit_lock(pid)
            self._lease_renew_at[pid] = time.monotonic()
            try:
                return self.engine.checkout(project)
            except Exception:
                if not held:
                    try:
                        self.api.release_edit_lock(pid)
                    except APIError:
                        pass
                raise

        def done(path):
            open_kicad(path)
            self._set_status("Exclusive editing lock acquired for " + project["name"])
            self._select(pid)
            self._refresh()

        self._task("Acquiring exclusive editing lock…", work, done)

    def _release_selected_lock(self):
        project = self._selected()
        if not project or not self.api or not self.engine:
            self._set_status("Select a project first.")
            return
        pid = project["id"]
        if not self.api.has_edit_lock(pid):
            self._set_status("You don't own this editing lock.")
            return
        if editor_running():
            messagebox.showwarning("TAUV", "Close KiCad schematic and PCB editors before unlocking.", parent=self)
            return
        if not messagebox.askyesno(
            "Release editing lock", "Allow other users to edit " + project["name"] + "?",
            parent=self):
            return

        def work():
            record = self.engine.local_projects().get(pid)
            if record:
                from .sync import stat_manifest, hash_manifest
                folder = self.engine.folder(pid)
                if hash_manifest(folder, stat_manifest(folder)) != record["files"]:
                    raise RuntimeError("Unsynchronized local changes. Sync and save before unlocking.")
            return self.api.release_edit_lock(pid)

        def done(_result):
            self._lease_renew_at.pop(pid, None)
            self._set_status("Editing lock released; project history is preserved.")
            self._refresh()

        self._task("Releasing editing lock…", work, done)

    def _admin_force_unlock(self):
        project = self._selected()
        if not project or not self.api:
            self._set_status("Select a project first.")
            return
        if self.user.get("role") != "admin":
            messagebox.showwarning("TAUV", "Only an administrator can force-unlock.", parent=self)
            return
        lock = project.get("edit_lock")
        if not lock:
            self._set_status("This project is not currently locked.")
            return
        if not messagebox.askyesno(
            "Administrator override",
            "Force-release the editing lock held by " + str(lock["owner"]) +
            "? Their KiCad editor may still be open. Their token will be invalidated; "
            "unsaved local changes must be preserved manually. Continue?",
            parent=self,
        ):
            return
        self._task("Administratively releasing lock…",
                   lambda: self.api.force_release_edit_lock(project["id"]),
                   lambda _: (self._set_status("Editing lock force-released."),
                              self._refresh()))

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
            self._set_status("Imported as " + project["name"] + ". Your original files are unchanged.")
            if messagebox.askyesno("TAUV", "Open the synchronized managed copy now?", parent=self):
                self._task("Acquiring edit lock…",
                           lambda: self.api.acquire_edit_lock(project["id"]),
                           lambda _lease: (self._lease_renew_at.__setitem__(
                               project["id"], time.monotonic()), open_kicad(path),
                               self._refresh()))
        def import_work():
            fresh = self.api.projects()
            unique_name = next_available_name(name, fresh)
            return self.engine.upload_local_project(project_file, unique_name)
        self._task("Importing existing project…", import_work, done)

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
            if not self.api.has_edit_lock(project["id"]):
                messagebox.showwarning("TAUV", "Open the project to acquire its edit lock before restoring.", parent=win)
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
        if self.api and self.api.edit_tokens and editor_running():
            messagebox.showwarning(
                "TAUV", "Close KiCad before signing out; sign-out stops lock renewal.",
                parent=self)
            return
        self.stop.set()
        if self.api:
            self.api.timeout = min(self.api.timeout, 5)
            self.api.release_all_edit_locks()
        if self.api:
            try:
                self.api.cookies.clear()
            except Exception:
                pass
        forget_login()
        self.connected = False
        self.destroy()  # restart the app to sign into a different account

    def _on_close(self):
        if self.api and self.api.edit_tokens and editor_running():
            messagebox.showwarning(
                "TAUV — Editing lock active",
                "Close all KiCad editors before quitting TAUV. Minimize TAUV "
                "to keep your exclusive editing locks alive.", parent=self)
            return
        if self.connected and not messagebox.askyesno(
            "Exit TAUV", "Exit TAUV and release editing locks?\n"
            "Close KiCad first; minimize TAUV to keep locks active.",
            parent=self):
            return
        self.stop.set()
        if self.api:
            self.api.timeout = min(self.api.timeout, 5)
            self.api.release_all_edit_locks()
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
