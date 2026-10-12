"""TAUVSYNC desktop project browser.

Launch: python -m tauvsync.app  (from the client/ directory)
The PCB Editor ActionPlugin launches this same process. The synchronization
worker runs while this application remains open or minimized.
"""
from __future__ import annotations

import json
import os
import argparse
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

from .api import APIError, PrismAPI
from .credentials import CredentialStoreUnavailable, store_login, load_login, forget_login
from .sync import SyncEngine, SyncUnsafe, editor_running, unavailable_cloud_status


SETTINGS = Path.home() / ".tauvsync-client.json"
DEFAULT_SERVER = "https://tauvsync-gateway.umutcanbahadir.workers.dev"
LOGO_PATH = Path(__file__).resolve().parent / "resources" / "tauv_icon_64.png"


def load_preferences() -> dict:
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_preferences(url: str, workspace: str, email: str, remember: bool):
    """Store UI settings only; credentials belong to Windows DPAPI.

    Legacy SSH configuration in pre-2.0 preferences is intentionally ignored
    and discarded the next time preferences are saved.
    """
    SETTINGS.write_text(json.dumps({
        "url": url, "workspace": workspace, "email": email, "remember": remember,
    }, indent=2), encoding="utf-8")


def find_project_file(candidate: Path | None) -> Path | None:
    """Derive the active KiCad project from PCB Editor's saved board filename."""
    if not candidate:
        return None
    candidate = Path(candidate).expanduser().resolve()
    if candidate.suffix.lower() == ".kicad_pro" and candidate.is_file():
        return candidate
    if candidate.suffix.lower() == ".kicad_pcb" and candidate.is_file():
        matching = candidate.with_suffix(".kicad_pro")
        if matching.is_file():
            return matching
        projects = list(candidate.parent.glob("*.kicad_pro"))
        if len(projects) == 1:
            return projects[0]
    return None


def open_kicad(path: Path):
    if not path.is_file() or path.suffix.lower() != ".kicad_pro":
        raise SyncUnsafe("Project file does not exist")
    if sys.platform == "win32":
        os.startfile(str(path))  # user-chosen local KiCad file association
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def run(project_path: str | None = None):
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog, simpledialog

    class Window:
        def __init__(self):
            self.root = tk.Tk()
            self.root.title("TAUV — KiCad Team Projects")
            self.root.geometry("880x630")
            self.root.minsize(680, 430)
            self.launch_project = Path(project_path) if project_path else None
            self.api = None
            self.engine = None
            self.user = None
            self.remote = []
            self.folders = []
            self.workspace_projects = []
            self.messages = queue.Queue()
            self.shutdown = threading.Event()
            self.sync_thread = None
            self.busy = False
            self.last_status = {}
            self.selected_id = None
            self._draw()
            self.root.protocol("WM_DELETE_WINDOW", self._close)
            self.root.after(250, self._consume)
            # One-time first-launch configuration remains manual. Subsequent
            # remembered sessions connect automatically on client launch.
            if self.remember.get() and self.password.get():
                self.root.after(350, self._login)

        def _draw(self):
            pref = load_preferences()
            outer = ttk.Frame(self.root, padding=12)
            outer.pack(fill="both", expand=True)
            heading = ttk.Frame(outer)
            heading.pack(fill="x", pady=(0, 10))
            self.logo = None
            try:
                self.logo = tk.PhotoImage(file=str(LOGO_PATH))
                self.root.iconphoto(True, self.logo)
                ttk.Label(heading, image=self.logo).pack(side="left", padx=(0, 12))
            except (OSError, tk.TclError):
                pass
            title = ttk.Frame(heading)
            title.pack(side="left", fill="x", expand=True)
            ttk.Label(title, text="TAUV", font=("Arial", 20, "bold")).pack(anchor="w")
            ttk.Label(title, text="Team Projects  •  KiCad 10 synchronization").pack(anchor="w")
            login = ttk.LabelFrame(outer, text="TAUV account", padding=10)
            login.pack(fill="x")
            self.url = tk.StringVar(value=pref.get("url") or DEFAULT_SERVER)
            self.email = tk.StringVar(value=pref.get("email", ""))
            self.remember = tk.BooleanVar(value=bool(pref.get("remember", False)))
            cached = load_login(pref.get("url") or DEFAULT_SERVER, pref.get("email", "")) if self.remember.get() else None
            self.password = tk.StringVar(value=cached or "")
            self.workspace = tk.StringVar(value=pref.get("workspace", str(Path.home() / "TAUVSYNC")))
            for row, (label, value, show) in enumerate((
                ("TAUV server", self.url, None), ("Email", self.email, None),
                ("Password", self.password, "*"), ("Local folder", self.workspace, None),
            )):
                ttk.Label(login, text=label).grid(row=row, column=0, sticky="w", pady=2, padx=4)
                entry = ttk.Entry(login, textvariable=value, show=show, width=62)
                entry.grid(row=row, column=1, sticky="ew", pady=2, padx=4)
            login.columnconfigure(1, weight=1)
            self.login_button = ttk.Button(login, text="Log in", command=self._login)
            self.login_button.grid(row=0, column=2, rowspan=2, padx=6)
            ttk.Checkbutton(login, text="Remember email and password (Windows encrypted storage)",
                            variable=self.remember, command=self._remember_changed).grid(
                                row=4, column=1, sticky="w", pady=3)
            ttk.Label(login, text="Session cookies remain in memory. Password is protected with Windows DPAPI.",
                      foreground="gray").grid(row=5, column=1, sticky="w")
            ttk.Label(outer, text="TAUV folders / shared KiCad projects",
                      font=("Arial", 12, "bold")).pack(anchor="w", pady=(12, 6))
            ttk.Button(outer, text="Upload current/open KiCad project to TAUVSYNC…",
                       command=self._upload_project).pack(anchor="w", pady=(0, 5))
            self.search = tk.StringVar()
            ttk.Entry(outer, textvariable=self.search, width=40).pack(
                fill="x", pady=(0, 6))
            self.tree = ttk.Treeview(outer, columns=("revision", "status"), show="tree headings", selectmode="browse")
            self.tree.heading("#0", text="Project / folder")
            self.tree.heading("revision", text="Cloud revision")
            self.tree.heading("status", text="Local status")
            self.tree.column("#0", width=380, stretch=True)
            self.tree.column("revision", width=110, stretch=False, anchor="center")
            self.tree.column("status", width=240, stretch=True)
            self.tree.pack(fill="both", expand=True)
            self.tree.bind("<<TreeviewSelect>>", self._selection)
            self.tree.bind("<Double-1>", lambda _event: self._open_project())
            self.search.trace_add("write", lambda *_: self._show_tree())

            toolbar = ttk.Frame(outer)
            toolbar.pack(fill="x", pady=(8, 4))
            actions = [
                ("Refresh cloud", self._refresh),
                ("Open in KiCad", self._open_project),
                ("Sync now", self._sync_now),
                ("Version history", self._history),
                ("Preserve conflict on server", self._alternate),
                ("Use latest server version", self._use_server),
            ]
            for label, fn in actions:
                ttk.Button(toolbar, text=label, command=fn).pack(side="left", padx=2)
            self.status = tk.StringVar(value="Sign in with your TAUV team account.")
            ttk.Label(outer, textvariable=self.status, wraplength=825).pack(anchor="w", pady=4)

        def _event(self, kind: str, obj):
            self.messages.put((kind, obj))

        def _background(self, work):
            if self.busy:
                return
            self.busy = True
            def worker():
                try:
                    result = work()
                    self._event("done", result)
                except Exception as error:
                    self._event("error", str(error))
                finally:
                    self._event("unbusy", None)
            threading.Thread(target=worker, daemon=True).start()

        def _remember_changed(self):
            if not self.remember.get():
                forget_login()
                self.password.set("")
                save_preferences(self.url.get().strip(), self.workspace.get().strip(),
                                 self.email.get().strip(), False)

        def _login(self):
            url = self.url.get().strip()
            email = self.email.get().strip()
            password = self.password.get()
            storage = self.workspace.get().strip()
            remember = bool(self.remember.get())
            self.password.set("")

            def task():
                api = PrismAPI(url)
                user = api.login(email, password)
                engine = SyncEngine(api, Path(storage))
                projects = api.projects()
                self.api, self.user, self.engine = api, user, engine
                save_preferences(url, storage, email, remember)
                warning = ""
                try:
                    if remember:
                        store_login(url, email, password)
                    else:
                        forget_login()
                except (OSError, CredentialStoreUnavailable) as error:
                    warning = f"; could not save password securely: {error}"
                return ("login", projects, warning)

            self.status.set("Connecting to TAUV…")
            self._background(task)

        def _upload_project(self):
            if not self.api or not self.engine:
                self.status.set("Sign in before uploading a KiCad project.")
                return
            if self.user.get("role") not in ("designer", "admin"):
                self.status.set("TAUV Designer or Admin permission is required for uploading.")
                return
            project_file = find_project_file(self.launch_project)
            if project_file and not messagebox.askyesno(
                "Current KiCad project", f"Upload the currently open project?\n{project_file}"
            ):
                project_file = None
            if project_file is None:
                chosen = filedialog.askopenfilename(
                    title="Select an existing KiCad 10 project",
                    filetypes=[("KiCad project", "*.kicad_pro")])
                if not chosen:
                    return
                project_file = find_project_file(Path(chosen))
            if not project_file:
                messagebox.showerror("Project not saved",
                                     "Save a complete KiCad .kicad_pro project first.")
                return
            name = simpledialog.askstring("Create team project", "Cloud project name:",
                                          initialvalue=project_file.stem, parent=self.root)
            if not name or not name.strip():
                return
            if not messagebox.askyesno("Upload and synchronize",
                    "Upload an archive of all project files?\n\n"
                    "Your original project folder will not be changed. "
                    "TAUVSYNC creates a managed copy in your configured local workspace. "
                    "To enable automatic synchronization, close the original project "
                    "and continue editing the managed copy."):
                return
            name = name.strip()
            def task():
                project, managed_path = self.engine.upload_local_project(project_file, name)
                return ("uploaded", project, str(managed_path))
            self.status.set("Archiving and uploading project…")
            self._background(task)

        def _refresh(self):
            if self.api:
                self._background_refresh_no_guard()

        def _background_refresh_no_guard(self):
            # The queue is the sole path back into Tk. Never block Tk waiting
            # for HTTP requests or call a Tk widget from a worker thread.
            def worker():
                try:
                    value = ("refresh", self.api.projects(),
                             self.api._json("/api/folders/tree"),
                             self.api._json("/api/projects/"))
                    self._event("done", value)
                except Exception as error:
                    self._event("error", str(error))
            threading.Thread(target=worker, daemon=True).start()

        def _show_tree(self):
            previous = self.selected_id
            self.tree.delete(*self.tree.get_children())
            # Prism folder structure is shown, including empty folders. Only
            # projects managed by TAUVSYNC appear in the cloud project list.
            mapping = {}
            prism_folders = {p.get("id"): p.get("folder_id") for p in self.workspace_projects}
            for folder in self.folders:
                parent = mapping.get(folder.get("parent_id"), "")
                key = "folder:" + folder["id"]
                self.tree.insert(parent, "end", iid=key, text="📁 " + folder["name"],
                                 values=("", ""))
                mapping[folder["id"]] = key
            local_projects = self.engine.local_projects() if self.engine else {}
            cloud_ids = set()
            removed = []
            search_text = self.search.get().strip().casefold()
            for project in self.remote:
                if search_text and search_text not in project.get("name", "").casefold():
                    continue
                pid = project["id"]
                cloud_ids.add(pid)
                unavailable = unavailable_cloud_status(project)
                if unavailable:
                    removed.append((project, unavailable))
                    continue
                fid = prism_folders.get(project.get("prism_project_id"))
                parent = mapping.get(fid, "")
                details = (self.engine.status.get(pid, "Downloaded; waiting for sync")
                           if pid in local_projects and self.engine else "Cloud only")
                self.tree.insert(parent, "end", iid="project:" + pid, text=project["name"],
                                 values=("r" + str(project["head_revision"]), details))

            # Prism is authoritative for active membership. Keep deleted
            # projects and local checkouts in a separate recovery section,
            # never erase their files or historical server revisions.
            missing = sorted(pid for pid in set(local_projects) - {p["id"] for p in self.remote}
                             if not search_text or search_text in (local_projects[pid].get("name") or pid).casefold())
            if removed or missing:
                group = "local:unavailable"
                self.tree.insert("", "end", iid=group,
                                 text="Removed from Prism / unavailable (sync paused)",
                                 values=("", ""))
                for project, unavailable in removed:
                    pid = project["id"]
                    details = (unavailable if pid in local_projects else
                               "Removed from Prism; no local checkout; server history retained")
                    self.tree.insert(group, "end", iid="project:" + pid,
                                     text=project["name"],
                                     values=("r" + str(project["head_revision"]), details))
                for pid in missing:
                    record = local_projects[pid]
                    self.tree.insert(group, "end", iid="project:" + pid,
                                     text=record.get("name") or pid,
                                     values=("r" + str(record.get("base_revision", "?")),
                                             unavailable_cloud_status(None)))
            if previous and self.tree.exists("project:" + previous):
                self.tree.selection_set("project:" + previous)

        def _selection(self, _event):
            selection = self.tree.selection()
            self.selected_id = selection[0][8:] if selection and selection[0].startswith("project:") else None

        def _remote_selected(self):
            return next((p for p in self.remote if p["id"] == self.selected_id), None)

        def _open_project(self):
            if not self.engine or not self.selected_id:
                return
            pid = self.selected_id
            project = self._remote_selected()
            unavailable = unavailable_cloud_status(project)
            if unavailable:
                if pid not in self.engine.local_projects():
                    self.status.set(unavailable + "; no managed checkout to open")
                    return
                def open_preserved():
                    record = self.engine._record(pid)
                    path = self.engine.folder(pid) / record["project_file"]
                    open_kicad(path)
                    return ("message", "Opened preserved local project; cloud sync is paused")
                self._background(open_preserved)
                return
            def task():
                path = self.engine.checkout(project)
                open_kicad(path)
                return ("message", "Opened " + project["name"] + " in KiCad")
            self._background(task)

        def _sync_now(self):
            if not self.engine or not self.selected_id:
                return
            project = self._remote_selected()
            unavailable = unavailable_cloud_status(project)
            if unavailable:
                self.status.set(unavailable)
                return
            pid = self.selected_id
            def task():
                return ("message", self.engine.poll(
                    pid, project, editors_open=editor_running(),
                    allow_publish=bool(self.user and self.user.get("role") in ("designer", "admin")),
                ))
            self._background(task)

        def _history(self):
            project = self._remote_selected()
            if not self.api or not project:
                self.status.set("Select a team project to view its revisions.")
                return
            self._background(lambda: ("history", project, self.api.revisions(project["id"])))

        def _show_history(self, project: dict, revisions: list[dict]):
            dialog = tk.Toplevel(self.root)
            dialog.title("TAUV — Version history: " + project["name"])
            dialog.geometry("690x430")
            dialog.transient(self.root)
            dialog.columnconfigure(0, weight=1)
            dialog.rowconfigure(1, weight=1)

            ttk.Label(
                dialog,
                text="Revision history — " + project["name"],
                font=("Arial", 13, "bold"),
            ).grid(row=0, column=0, sticky="w", padx=12, pady=(12, 8))
            table = ttk.Treeview(
                dialog, columns=("status", "author", "date", "based"),
                show="tree headings", selectmode="browse",
            )
            table.heading("#0", text="Revision")
            table.heading("status", text="Status")
            table.heading("author", text="Author")
            table.heading("date", text="Timestamp (UTC)")
            table.heading("based", text="Based on")
            table.column("#0", width=90, stretch=False)
            table.column("status", width=95, stretch=False)
            table.column("author", width=200)
            table.column("date", width=210)
            table.column("based", width=85, stretch=False)
            table.grid(row=1, column=0, sticky="nsew", padx=12)
            for revision in revisions:
                number = int(revision["number"])
                table.insert("", "end", iid=str(number), text="r" + str(number),
                             values=(revision.get("status", ""),
                                     revision.get("author", ""),
                                     revision.get("created_at", ""),
                                     revision.get("based_on") or "—"))

            def selected_revision() -> int | None:
                selected = table.selection()
                return int(selected[0]) if selected else None

            def save_snapshot():
                number = selected_revision()
                if number is None:
                    return
                target = filedialog.asksaveasfilename(
                    parent=dialog, title="Download historical snapshot",
                    initialfile=f"{project['name']}-r{number}.zip",
                    defaultextension=".zip", filetypes=[("ZIP snapshot", "*.zip")],
                )
                if not target:
                    return
                def operation():
                    self.api.download(project["id"], number, Path(target))
                    return ("message", f"Downloaded r{number} to {target}")
                self._background(operation)

            def restore_snapshot():
                number = selected_revision()
                if number is None:
                    return
                if not messagebox.askyesno(
                    "Restore historical version",
                    f"Restore r{number} as a NEW latest cloud revision? "
                    "Existing history will remain available.",
                    parent=dialog,
                ):
                    return
                def operation():
                    result = self.api.restore(project["id"], number)
                    self._event("message", f"Restored r{number} as r{result['number']}")
                    self._background_refresh_no_guard()
                    return ("message", "Restore completed; all earlier versions retained.")
                self._background(operation)

            buttons = ttk.Frame(dialog)
            buttons.grid(row=2, column=0, sticky="ew", padx=12, pady=12)
            ttk.Button(buttons, text="Download ZIP", command=save_snapshot).pack(side="left")
            can_restore = bool(self.user and self.user.get("role") in ("designer", "admin")
                               and project.get("cloud_state", "active") == "active")
            restore_btn = ttk.Button(buttons, text="Restore as latest revision",
                                     command=restore_snapshot)
            restore_btn.pack(side="left", padx=8)
            if not can_restore:
                restore_btn.state(["disabled"])
            ttk.Button(buttons, text="Close", command=dialog.destroy).pack(side="right")
            if revisions:
                table.selection_set(str(revisions[0]["number"]))

        def _alternate(self):
            if not self.engine or not self.selected_id:
                return
            project = self._remote_selected()
            unavailable = unavailable_cloud_status(project)
            if unavailable:
                self.status.set(unavailable)
                return
            if not self.engine._record(self.selected_id).get("conflict"):
                self.status.set("No unresolved conflict for this project.")
                return
            if not messagebox.askyesno("Preserve local work", "Publish local files as a separate alternate revision? This will not overwrite the server's current design."):
                return
            self._background(lambda: ("message",
                str(self.engine.preserve_local_on_server(self.selected_id))))

        def _use_server(self):
            if not self.engine or not self.selected_id:
                return
            project = self._remote_selected()
            unavailable = unavailable_cloud_status(project)
            if unavailable:
                self.status.set(unavailable)
                return
            if not messagebox.askyesno("Use server revision",
                "Keep a full local backup and replace your working folder with the server's latest revision? Close all KiCad editors first."):
                return
            def task():
                self.engine.resolve_use_server(self.selected_id, project, editors_open=editor_running())
                return ("message", "Latest server revision installed; previous local files backed up.")
            self._background(task)

        def _sync_loop(self):
            while not self.shutdown.is_set():
                if self.api and self.engine:
                    try:
                        projects = self.api.projects()
                        pmap = {p["id"]: p for p in projects}
                        for pid in self.engine.local_projects():
                            unavailable = unavailable_cloud_status(pmap.get(pid))
                            if unavailable:
                                self.engine.status[pid] = unavailable
                                if self.last_status.get(pid) != unavailable:
                                    self.last_status[pid] = unavailable
                                    self._event("message", unavailable)
                                continue
                            try:
                                status = self.engine.poll(
                                    pid, pmap[pid], editors_open=editor_running(),
                                    allow_publish=self.user.get("role") in ("designer", "admin"),
                                )
                                if self.last_status.get(pid) != status:
                                    self.last_status[pid] = status
                                    self._event("message", f"{pmap[pid]['name']}: {status}")
                            except Exception as exc:
                                self._event("message", f"{pmap[pid]['name']}: {exc}; local files retained")
                        self._event("remote", projects)
                    except Exception as exc:
                        self._event("message", "Sync paused: " + str(exc) + "; retrying automatically")
                self.shutdown.wait(5)

        def _consume(self):
            try:
                while True:
                    kind, payload = self.messages.get_nowait()
                    if kind == "done":
                        if payload and payload[0] == "login":
                            self.remote = payload[1]
                            self.status.set(f"Connected as {self.user['email']}{payload[2]}")
                            if not self.sync_thread or not self.sync_thread.is_alive():
                                self.sync_thread = threading.Thread(target=self._sync_loop, daemon=True)
                                self.sync_thread.start()
                            # Unbusy arrives later; load folder metadata without
                            # dropping the request behind the busy guard.
                            self._background_refresh_no_guard()
                        elif payload and payload[0] == "uploaded":
                            _, project, managed_path = payload
                            self.remote = [p for p in self.remote if p["id"] != project["id"]] + [project]
                            self.selected_id = project["id"]
                            self.status.set(
                                "Uploaded successfully. Managed KiCad project: " + managed_path +
                                ". Close the original PCB Editor, then use Open in KiCad "
                                "on this project to edit the synchronized copy.")
                        elif payload and payload[0] == "history":
                            _, project, revisions = payload
                            self._show_history(project, revisions)
                        elif payload and payload[0] == "refresh":
                            _, self.remote, self.folders, self.workspace_projects = payload
                        elif payload and payload[0] == "message":
                            self.status.set(payload[1])
                        self._show_tree()
                    elif kind == "remote":
                        self.remote = payload
                        self._show_tree()
                    elif kind in ("error", "message"):
                        self.status.set(str(payload))
                    elif kind == "unbusy":
                        self.busy = False
            except queue.Empty:
                pass
            if not self.shutdown.is_set():
                self.root.after(250, self._consume)

        def _close(self):
            if self.engine and not messagebox.askyesno(
                "Exit TAUVSYNC", "Stop automatic project synchronization? You can also minimize this window to keep syncing."
            ):
                return
            self.shutdown.set()
            self.root.destroy()

    from .instance import AlreadyRunning, single_instance, focus_existing_window
    try:
        with single_instance():
            Window().root.mainloop()
    except AlreadyRunning as error:
        if not focus_existing_window("TAUV — KiCad Team Projects"):
            messagebox.showinfo("TAUV", str(error))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", help="Current PCB file passed by KiCad 10")
    args = parser.parse_args()
    run(args.project)
