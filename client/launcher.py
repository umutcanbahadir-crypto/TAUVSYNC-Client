"""TAUVSYNC executable launch and diagnostics for the KiCad 10 IPC action.

The GUI is intentionally packaged with PyInstaller --windowed. Because a
windowed build has no console, all boot-time exceptions must be written to a
user-owned local log and explained with a native Windows error dialog.

No credentials, API tokens, IPC paths or server request data are logged.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from multiprocessing import freeze_support
import os
from pathlib import Path
import sys
import traceback


def log_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "TAUVSYNC" / "logs" / "launcher.log"


def log_event(message: str) -> None:
    """Record only bootstrap events; keep a bounded log on each launch."""
    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file() and path.stat().st_size > 512 * 1024:
            path.replace(path.with_suffix(".previous.log"))
        with path.open("a", encoding="utf-8") as handle:
            timestamp = datetime.now(timezone.utc).isoformat()
            handle.write(f"{timestamp} {message}\n")
    except OSError:
        pass


def show_startup_failure() -> None:
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                None,
                "TAUV Team Projects could not start.\n\n"
                "The error was saved to:\n" + str(log_path()) + "\n\n"
                "Send the error text to the TAUV administrator.",
                "TAUV — Startup error", 0x10,
            )
            return
        except Exception:
            pass


def current_project_from_kicad() -> Path | None:
    """Best-effort KiCad IPC context lookup. Works without an active PCB."""
    if not os.environ.get("KICAD_API_SOCKET"):
        return None
    try:
        from kipy import KiCad
        board = KiCad().get_board()
        if board is None:
            return None
        project = board.get_project()
        project_path = Path(project.path)
        for candidate in (
            project_path,
            project_path / (project.name + ".kicad_pro"),
            Path(board.name).with_suffix(".kicad_pro"),
        ):
            if candidate.suffix.casefold() == ".kicad_pro" and candidate.is_file():
                return candidate.resolve()
    except Exception:
        # KiCad API context is optional for browsing cloud projects.
        return None
    return None


def runtime_self_test() -> None:
    """Exercise the actual frozen runtime without needing KiCad or a network."""
    from tauvsync.app import LOGO_PATH, DEFAULT_SERVER
    import customtkinter
    from PIL import Image
    from tauvsync.api import PrismAPI
    from tauvsync.launcher_ui import Workspace
    import tkinter

    assert LOGO_PATH.is_file(), "TAUV icon missing from bundled executable"
    assert LOGO_PATH.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"), "TAUV icon invalid"
    assert DEFAULT_SERVER.startswith("https://"), "Invalid HTTPS server setting"
    PrismAPI(DEFAULT_SERVER)
    interpreter = tkinter.Tcl()
    assert interpreter.eval("info patchlevel"), "Tkinter Tcl runtime missing"
    log_event("SELF-TEST OK: bundled icon, HTTPS client and Tcl runtime")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    options, _unknown = parser.parse_known_args(argv)
    log_event("Starting TAUVSYNC executable")

    try:
        if options.self_test:
            runtime_self_test()
            return 0

        # Import Tkinter and application resources here, inside the crash
        # reporter, rather than at module import time.
        from tauvsync.launcher_ui import run_launcher
        project = current_project_from_kicad()
        log_event("Launching TAUV dashboard")
        run_launcher(str(project) if project else None)
        log_event("TAUV dashboard closed normally")
        return 0
    except Exception:
        log_event("STARTUP FAILURE:\n" + traceback.format_exc())
        show_startup_failure()
        return 1


if __name__ == "__main__":
    freeze_support()
    raise SystemExit(main())
