"""Launch saved KiCad 10 projects with the KiCad 10 Project Manager.

Never use os.startfile(.kicad_pro) on Windows: Windows file associations may
still point to KiCad 9 even when KiCad 10 is installed side by side.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def find_kicad10(*, environ: dict[str, str] | None = None) -> Path:
    """Find KiCad 10's actual Project Manager executable (not the file association)."""
    env = os.environ if environ is None else environ
    override = env.get("TAUV_KICAD10_EXE")
    if override:
        candidate = Path(override).expanduser()
        if candidate.is_file() and candidate.name.casefold() == "kicad.exe":
            return candidate.resolve()
        raise FileNotFoundError("TAUV_KICAD10_EXE must point to KiCad 10's kicad.exe")

    roots: list[Path] = []
    for variable in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)"):
        if env.get(variable):
            roots.append(Path(env[variable]))
    if env.get("LOCALAPPDATA"):
        roots.append(Path(env["LOCALAPPDATA"]) / "Programs")
    for root in roots:
        candidate = root / "KiCad" / "10.0" / "bin" / "kicad.exe"
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(
        "KiCad 10 is not installed in the standard Windows location. "
        "Install KiCad 10, or set TAUV_KICAD10_EXE to the full path of "
        "KiCad 10's kicad.exe (never the KiCad 9 executable)."
    )


def launch_kicad_project(path: Path, *, platform: str | None = None,
                         environ: dict[str, str] | None = None):
    project = Path(path).expanduser().resolve()
    if not project.is_file() or project.suffix.casefold() != ".kicad_pro":
        raise FileNotFoundError("Select an existing .kicad_pro KiCad project")
    platform = platform or sys.platform
    if platform == "win32":
        return subprocess.Popen([str(find_kicad10(environ=environ)), str(project)],
                                close_fds=True,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
    if platform == "darwin":
        return subprocess.Popen(["open", str(project)])
    return subprocess.Popen(["xdg-open", str(project)])
