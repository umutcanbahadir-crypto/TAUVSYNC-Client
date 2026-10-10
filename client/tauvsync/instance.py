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
