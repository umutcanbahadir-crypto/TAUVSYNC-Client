"""Local-first KiCad project synchronization engine.

* Saves on disk are discovered automatically; no Git or ZIP workflow in UI.
* Uploads only after files stop changing; server keeps immutable history.
* Incoming server revisions are downloaded automatically.
* Remote changes NEVER overwrite edits or a running KiCad editor.
* Dirty+remote-newer becomes a conflict, with explicit backup-preserving recovery.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path, PurePosixPath
from threading import RLock
from time import monotonic
from typing import Callable
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

MAX_FILE = 256 * 1024 ** 2
MAX_TOTAL = 512 * 1024 ** 2
MAX_FILES = 12000
WINDOWS_BAD = re.compile(r'[<>:"|?*\\\x00-\x1f]')
RESERVED = re.compile(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$', re.I)


class SyncUnsafe(ValueError):
    pass


class SyncConflict(RuntimeError):
    pass


def unavailable_cloud_status(remote: dict | None) -> str | None:
    """A missing Prism registration is not an instruction to erase local data.

    The backend keeps Git history after deletion in Prism. The sync client
    must stop publishing and visibly retain the checkout for recovery.
    """
    if remote is None:
        return "No longer available in cloud; local copy preserved (sync paused)"
    if remote.get("cloud_state") == "missing_prism":
        return "Removed from TAUV cloud; local copy preserved (sync paused)"
    if remote.get("cloud_state") == "unregistered":
        return "Not registered in TAUV cloud; local copy preserved (sync paused)"
    return None


def ignored(name: str, *, is_dir: bool = False) -> bool:
    lower = name.casefold()
    if lower in (".git", ".tauvsync", "__pycache__", ".ds_store", "thumbs.db"):
        return True
    if is_dir:
        return lower.endswith("-backups") or lower in (".git", ".tauvsync")
    return (
        name.startswith("~") or lower.startswith("~$") or
        lower.endswith((".kicad_prl", ".lck", ".lock", ".tmp", ".bak", ".swp", ".pyc")) or
        lower.endswith(("-bak", "-autosave")) or lower.startswith("_autosave-")
    )


def _parts(name: str) -> tuple[str, ...]:
    if not name or len(name.encode("utf-8")) > 1024 or "\\" in name or name.startswith("/"):
        raise SyncUnsafe("Unsafe archive pathname")
    pieces = name.rstrip("/").split("/")
    if any(part in ("", ".", "..") for part in pieces):
        raise SyncUnsafe("Archive contains traversal or ambiguous path")
    for part in pieces:
        if WINDOWS_BAD.search(part) or RESERVED.match(part) or part.endswith((" ", ".")):
            raise SyncUnsafe("Archive contains an unsupported Windows filename")
        if part.casefold() in (".git", ".ssh", ".tauvsync"):
            raise SyncUnsafe("Archive contains a prohibited internal directory")
    return tuple(pieces)


def safe_extract(archive: Path, destination: Path) -> str:
    """Reject unsafe paths, symlinks, duplicate/case-colliding files and zip bombs."""
    if destination.exists():
        raise FileExistsError(destination)
    destination.mkdir(mode=0o700)
    seen = set()
    projects = []
    total = count = 0
    try:
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                pieces = _parts(info.filename)
                key = "/".join(pieces).casefold()
                if key in seen:
                    raise SyncUnsafe("Duplicate ZIP entry")
                seen.add(key)
                mode = (info.external_attr >> 16) & 0xFFFF
                kind = stat.S_IFMT(mode)
                if kind not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise SyncUnsafe("ZIP symlinks and special files are prohibited")
                if info.flag_bits & 1:
                    raise SyncUnsafe("Encrypted ZIP is not supported")
                if info.file_size > MAX_FILE or (
                    info.file_size and info.file_size / max(info.compress_size, 1) > 250
                ):
                    raise SyncUnsafe("ZIP member exceeds size or compression limits")
                target = destination.joinpath(*pieces)
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                count += 1
                total += info.file_size
                if count > MAX_FILES or total > MAX_TOTAL:
                    raise SyncUnsafe("ZIP exceeds extraction limits")
                target.parent.mkdir(parents=True, exist_ok=True)
                written = 0
                with z.open(info) as source, target.open("xb") as dest:
                    while data := source.read(1024 * 1024):
                        written += len(data)
                        if written > info.file_size:
                            raise SyncUnsafe("Invalid member size")
                        dest.write(data)
                if written != info.file_size:
                    raise SyncUnsafe("Truncated ZIP entry")
                if info.filename.lower().endswith(".kicad_pro"):
                    projects.append("/".join(pieces))
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    if len(projects) != 1:
        shutil.rmtree(destination, ignore_errors=True)
        raise SyncUnsafe("Expected exactly one KiCad .kicad_pro file")
    return projects[0]


def stat_manifest(root: Path) -> dict[str, tuple[int, int]]:
    """A cheap scan for debouncing, independent of KiCad plugin callbacks."""
    result = {}
    folded_names = set()
    total = 0
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not ignored(d, is_dir=True))
        for directory in dirs:
            if (Path(current) / directory).is_symlink():
                raise SyncUnsafe("Symlinks cannot be synchronized")
        for filename in sorted(files):
            if ignored(filename):
                continue
            path = Path(current) / filename
            if path.is_symlink():
                raise SyncUnsafe("Symlinks cannot be synchronized")
            if not path.is_file():
                raise SyncUnsafe("Special file cannot be synchronized")
            relative = path.relative_to(root).as_posix()
            _parts(relative)
            st = path.stat()
            if st.st_size > MAX_FILE:
                raise SyncUnsafe("File exceeds 256 MiB")
            total += st.st_size
            if total > MAX_TOTAL or len(result) >= MAX_FILES:
                raise SyncUnsafe("Project exceeds 512 MiB / 12,000 files")
            folded = relative.casefold()
            if folded in folded_names:
                raise SyncUnsafe("Case-insensitive filename collision")
            folded_names.add(folded)
            result[relative] = (st.st_size, st.st_mtime_ns)
    if len([n for n in result if n.casefold().endswith(".kicad_pro")]) != 1:
        raise SyncUnsafe("A complete KiCad project (.kicad_pro) is required")
    return result


def hash_manifest(root: Path, stats: dict[str, tuple[int, int]]) -> dict[str, str]:
    output = {}
    for name, old_stat in stats.items():
        file = root.joinpath(*PurePosixPath(name).parts)
        digest = sha256()
        with file.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        st = file.stat()
        if (st.st_size, st.st_mtime_ns) != old_stat:
            raise SyncUnsafe("Project changed while scanning; retry later")
        output[name] = digest.hexdigest()
    if stat_manifest(root) != stats:
        raise SyncUnsafe("Files changed while scanning; retry later")
    return output


def package_project(root: Path, archive: Path) -> tuple[dict[str, str], dict[str, tuple[int, int]]]:
    stats = stat_manifest(root)
    hashes = hash_manifest(root, stats)
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=5) as out:
        for relative in sorted(stats):
            out.write(root.joinpath(*PurePosixPath(relative).parts), relative)
    if stat_manifest(root) != stats:
        archive.unlink(missing_ok=True)
        raise SyncUnsafe("Project was being edited during packaging")
    return hashes, stats


def editor_running() -> bool:
    """Conservative: block incoming replacements whenever ANY KiCad editor runs."""
    try:
        if sys.platform == "win32":
            p = subprocess.run(["tasklist", "/FO", "CSV", "/NH"],
                               capture_output=True, text=True, timeout=5)
            return any('"' + process + '"' in p.stdout.casefold()
                       for process in ("pcbnew.exe", "eeschema.exe"))
        p = subprocess.run(["pgrep", "-f", r"(^|/)(pcbnew|eeschema)( |$)"],
                           capture_output=True, timeout=5)
        return p.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        # Do not claim an editor is closed when we cannot verify it.
        return True


class SyncEngine:
    def __init__(self, api, workspace: Path, *,
                 settle_seconds: float = 8.0, clock: Callable[[], float] = monotonic):
        self.api = api
        self.root = Path(workspace).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.internal = self.root / ".tauvsync"
        self.internal.mkdir(exist_ok=True)
        self.stage = self.internal / "staging"
        self.stage.mkdir(exist_ok=True)
        self.backups = self.internal / "backups"
        self.backups.mkdir(exist_ok=True)
        self.state_path = self.internal / "state.json"
        self.lock = RLock()
        self.settle_seconds = settle_seconds
        self.clock = clock
        self._watch = {}
        self.status = {}
        self.state = {"projects": {}}
        if self.state_path.exists():
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("projects"), dict):
                self.state = data

    def _write_state(self):
        fd, name = tempfile.mkstemp(prefix="state-", suffix=".json", dir=self.internal)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(self.state, stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.state_path)
        finally:
            Path(name).unlink(missing_ok=True)

    def local_projects(self) -> dict[str, dict]:
        return dict(self.state["projects"])

    def _record(self, project_id: str) -> dict:
        if not re.fullmatch(r"[a-f0-9]{32}", project_id):
            raise SyncUnsafe("Invalid project ID")
        record = self.state["projects"].get(project_id)
        if not record:
            raise SyncUnsafe("Project is not checked out")
        return record

    def folder(self, project_id: str) -> Path:
        record = self._record(project_id)
        path = (self.root / record["folder"]).resolve()
        if path.parent != self.root:
            raise SyncUnsafe("Project path outside workspace")
        return path

    def _stage_remote(self, project_id: str, revision: int) -> Path:
        # Cached remote download is kept OUTSIDE the live KiCad project.
        destination = self.stage / f"{project_id}-r{revision}.zip"
        if destination.exists():
            return destination
        temp = self.stage / f"dl-{next(tempfile._get_candidate_names())}.zip"
        try:
            self.api.download(project_id, revision, temp)
            with zipfile.ZipFile(temp):
                pass
            temp.replace(destination)
        finally:
            temp.unlink(missing_ok=True)
        return destination

    def _prepare_download(self, project_id: str, revision: int) -> tuple[Path, str]:
        archive = self._stage_remote(project_id, revision)
        folder = Path(tempfile.mkdtemp(prefix="incoming-", dir=self.stage))
        output = folder / "contents"
        try:
            project_file = safe_extract(archive, output)
            return output, project_file
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise

    def checkout(self, project: dict) -> Path:
        project_id = project["id"]
        with self.lock:
            if project_id in self.state["projects"]:
                return self.folder(project_id) / self._record(project_id)["project_file"]
            slug = re.sub(r"[^A-Za-z0-9_-]+", "-", project.get("name", "project")).strip("-")[:48] or "project"
            directory = f"{slug}--{project_id[:12]}"
            target = self.root / directory
            if target.exists():
                raise SyncUnsafe("Existing checkout folder cannot be overwritten")
            revision = int(project["head_revision"])
            source, anchor = self._prepare_download(project_id, revision)
            try:
                hashes = hash_manifest(source, stat_manifest(source))
                source.rename(target)
                self.state["projects"][project_id] = {
                    "folder": directory, "project_file": anchor,
                    "base_revision": revision, "files": hashes,
                    "name": project.get("name", project_id), "conflict": False,
                }
                self._write_state()
                self.status[project_id] = f"Synced r{revision}"
                return target.joinpath(*PurePosixPath(anchor).parts)
            finally:
                if source.parent.exists():
                    shutil.rmtree(source.parent, ignore_errors=True)

    def upload_local_project(self, project_file: Path, name: str) -> tuple[dict, Path]:
        """Archive a saved local project, upload it and checkout a synced copy.

        The original folder remains untouched. Only the managed checkout is
        automatically synchronized, avoiding overwrite of an open PCB Editor.
        """
        project_file = Path(project_file).expanduser().resolve()
        if project_file.suffix.casefold() != ".kicad_pro" or not project_file.is_file():
            raise SyncUnsafe("Choose a saved .kicad_pro file")
        with self.lock:
            archive = self.stage / f"upload-{next(tempfile._get_candidate_names())}.zip"
            try:
                package_project(project_file.parent, archive)
                result = self.api.create(name, archive)
                project = result["project"]
                managed_file = self.checkout(project)
                return project, managed_file
            finally:
                archive.unlink(missing_ok=True)

    def _install_remote(self, project_id: str, revision: int):
        record = self._record(project_id)
        source, anchor = self._prepare_download(project_id, revision)
        target = self.folder(project_id)
        # Preserve local and all historical files; even a clean checkout has
        # rollback protection against interruption during rename.
        backup = self.backups / f"{project_id}-r{record['base_revision']}-{next(tempfile._get_candidate_names())}"
        old_moved = False
        try:
            hashes = hash_manifest(source, stat_manifest(source))
            if anchor != record["project_file"]:
                raise SyncConflict("Remote project was renamed; manual resolution required")
            target.rename(backup)
            old_moved = True
            try:
                source.rename(target)
            except Exception:
                backup.rename(target)
                old_moved = False
                raise
            record["base_revision"] = revision
            record["files"] = hashes
            record["conflict"] = False
            self._write_state()
            self.status[project_id] = f"Auto-updated to r{revision} (previous copy backed up)"
        finally:
            if source.parent.exists():
                shutil.rmtree(source.parent, ignore_errors=True)

    def poll(self, project_id: str, remote: dict, *, editors_open: bool,
             allow_publish: bool = True) -> str:
        """One deterministic sync tick; caller catches network errors and retries."""
        with self.lock:
            record = self._record(project_id)
            unavailable = unavailable_cloud_status(remote)
            if unavailable:
                self.status[project_id] = unavailable
                return unavailable
            folder = self.folder(project_id)
            stats = stat_manifest(folder)
            now = self.clock()
            last = self._watch.get(project_id)
            if last is None or last[0] != stats:
                self._watch[project_id] = (stats, now)
            hashes = hash_manifest(folder, stats)
            dirty = hashes != record["files"]
            head = int(remote["head_revision"])
            base = int(record["base_revision"])

            if record.get("conflict"):
                self.status[project_id] = "Conflict: local files protected; resolve manually"
                return self.status[project_id]
            if head != base:
                self._stage_remote(project_id, head)
                if dirty:
                    record["conflict"] = True
                    self._write_state()
                    self.status[project_id] = f"Conflict: server r{head}, local based on r{base}"
                elif editors_open:
                    self.status[project_id] = f"Incoming r{head} downloaded; waiting for KiCad editors to close"
                else:
                    self._install_remote(project_id, head)
                return self.status[project_id]
            if dirty and allow_publish:
                if now - self._watch[project_id][1] < self.settle_seconds:
                    self.status[project_id] = "Waiting for saved files to settle"
                else:
                    fd, filename = tempfile.mkstemp(prefix="outgoing-", suffix=".zip", dir=self.stage)
                    os.close(fd)
                    archive = Path(filename)
                    archive.unlink()  # package_project uses mode x, never overwrite
                    try:
                        included, _ = package_project(folder, archive)
                        result = self.api.publish(project_id, base, archive)
                        if result["status"] == "alternate":
                            record["conflict"] = True
                            record["alternate_revision"] = result["number"]
                            self._write_state()
                            self.status[project_id] = "Conflict: saved alternate server revision; manual merge required"
                        else:
                            record["base_revision"] = result["number"]
                            record["files"] = included
                            self._write_state()
                            self.status[project_id] = f"Published r{result['number']}"
                    finally:
                        archive.unlink(missing_ok=True)
                return self.status[project_id]
            self.status[project_id] = f"Synced r{base}" if not dirty else "Local changes pending"
            return self.status[project_id]

    def resolve_use_server(self, project_id: str, remote: dict, *, editors_open: bool):
        """Explicit local recovery: keep local backup and use latest remote."""
        if editors_open:
            raise SyncUnsafe("Close PCB and schematic editors before replacing local files")
        with self.lock:
            self._install_remote(project_id, int(remote["head_revision"]))

    def preserve_local_on_server(self, project_id: str) -> dict:
        """Explicitly publish divergent local work as a non-current server revision."""
        with self.lock:
            record = self._record(project_id)
            fd, path = tempfile.mkstemp(prefix="alternate-", suffix=".zip", dir=self.stage)
            os.close(fd)
            archive = Path(path)
            archive.unlink()
            try:
                package_project(self.folder(project_id), archive)
                result = self.api.publish(project_id, int(record["base_revision"]), archive)
                if result["status"] == "alternate":
                    record["alternate_revision"] = result["number"]
                    record["conflict"] = True
                    self._write_state()
                    self.status[project_id] = f"Your work preserved as alternate r{result['number']}"
                return result
            finally:
                archive.unlink(missing_ok=True)
