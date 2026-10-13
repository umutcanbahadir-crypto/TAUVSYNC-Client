"""Cross-platform process lock: one sync client per Windows/Linux/macOS user.

Never allow two background monitors to upload from the same workspace.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import hashlib
import os
import sys
import tempfile


class AlreadyRunning(RuntimeError):
    pass


@contextmanager
def single_instance():
    home_id = hashlib.sha256(str(Path.home()).encode("utf-8")).hexdigest()[:16]
    location = Path(tempfile.gettempdir()) / f"tauvsync-{home_id}.lock"
    with location.open("a+b") as handle:
        handle.seek(0)
        if sys.platform == "win32":
            import msvcrt
            try:
                if handle.seek(0, os.SEEK_END) == 0:
                    handle.write(b"\x00")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise AlreadyRunning("TAUVSYNC is already running; use the existing window") from exc
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise AlreadyRunning("TAUVSYNC is already running; use the existing window") from exc
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def focus_existing_window(title: str) -> bool:
    """Best-effort focus for an already running Windows TAUV dashboard.

    Launching the plugin again must not create a second sync engine. This
    helper does not require pywin32 or elevated privileges.
    """
    if sys.platform != "win32":
        return False
    import ctypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    user32.FindWindowW.restype = ctypes.c_void_p
    hwnd = user32.FindWindowW(None, title)
    if not hwnd:
        return False
    user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE: restore a minimized dashboard
    user32.SetForegroundWindow(hwnd)
    return True
