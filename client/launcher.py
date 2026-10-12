"""KiCad 10 IPC executable entry point for TAUV Team Projects.

Launched as a self-contained Windows executable from the IPC plugin's action.
If the KiCad API is available, identify the currently open project so the
"Upload current project" action behaves like the legacy PCB Editor plugin.
"""
from __future__ import annotations

from multiprocessing import freeze_support
from pathlib import Path
import os

from tauvsync.app import run


def current_project_from_kicad() -> Path | None:
    if not os.environ.get("KICAD_API_SOCKET"):
        return None
    try:
        from kipy import KiCad
        board = KiCad().get_board()
        if board is None:
            return None
        project = board.get_project()
        project_path = Path(project.path)
        candidates = (
            project_path,
            project_path / (project.name + ".kicad_pro"),
            Path(board.name).with_suffix(".kicad_pro"),
        )
        for candidate in candidates:
            if candidate.suffix.casefold() == ".kicad_pro" and candidate.is_file():
                return candidate.resolve()
    except Exception:
        # Do not prevent access to the team dashboard if KiCad's API server
        # isn't enabled, the IPC bindings are unavailable, or no board is open.
        return None
    return None


if __name__ == "__main__":
    freeze_support()
    active = current_project_from_kicad()
    run(str(active) if active else None)
