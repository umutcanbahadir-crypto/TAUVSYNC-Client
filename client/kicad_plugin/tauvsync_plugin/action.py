"""KiCad 10-only PCB Editor launcher; synchronization runs externally."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pcbnew


class TauvsyncAction(pcbnew.ActionPlugin):
    def defaults(self):
        self.name = "TAUV — Team Projects"
        self.category = "Collaboration"
        self.description = "Open TAUV team projects and synchronize KiCad designs"
        self.show_toolbar_button = True
        self.icon_file_name = str(Path(__file__).resolve().parent / "tauvsync" / "resources" / "tauv_icon_24.png")

    def Run(self):
        build = str(pcbnew.GetBuildVersion())
        if not build.startswith("10."):
            raise RuntimeError("TAUVSYNC requires KiCad 10, got " + build)
        package_root = Path(__file__).resolve().parent
        if not (package_root / "tauvsync" / "app.py").is_file():
            raise RuntimeError("TAUVSYNC client missing; rerun the installer")
        # Prefer a bundled executable when this legacy launcher is installed
        # alongside a standalone distribution, but retain Python fallback for
        # existing development installations.
        executable = package_root / "TAUVSYNC" / "TAUVSYNC.exe"
        if executable.is_file():
            subprocess.Popen([str(executable)], cwd=str(package_root), close_fds=True)
            return
        candidates = (
            [["py", "-3"], ["python"], [sys.executable]]
            if os.name == "nt" else [["python3"], [sys.executable]]
        )
        for candidate in candidates:
            try:
                kwargs = {"cwd": str(package_root), "close_fds": True}
                if os.name == "nt":
                    kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                board = pcbnew.GetBoard()
                filename = str(board.GetFileName() or "") if board else ""
                command = candidate + ["-m", "tauvsync.app"]
                if filename:
                    command += ["--project", str(Path(filename).resolve())]
                subprocess.Popen(command, **kwargs)
                return
            except OSError:
                continue
        raise RuntimeError("Python 3 with Tkinter must be installed to run TAUVSYNC")
