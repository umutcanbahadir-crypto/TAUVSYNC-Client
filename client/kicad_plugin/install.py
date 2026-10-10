"""User-scope KiCad action plugin installer.

Run from the TAUVSYNC repository root:
  python client/kicad_plugin/install.py 10.0

No admin privileges required. Backs up an older plugin install, never erases
user project folders. Schematic Editor has no equivalent toolbar in KiCad 10.
"""
from pathlib import Path
from shutil import copytree
import os
import sys


def plugin_path(version: str) -> Path:
    if version != "10.0":
        raise ValueError("Only KiCad 10.0 is supported")
    if os.name == "nt":
        # Windows "Documents" may be redirected to OneDrive by the shell.
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
        ) as key:
            documents = os.path.expandvars(winreg.QueryValueEx(key, "Personal")[0])
        return Path(documents) / "KiCad" / version / "scripting" / "plugins" / "tauvsync_plugin"
    if sys.platform == "darwin":
        return Path.home() / "Documents" / "KiCad" / version / "scripting" / "plugins" / "tauvsync_plugin"
    return Path.home() / ".local" / "share" / "kicad" / version / "scripting" / "plugins" / "tauvsync_plugin"


def install(version: str):
    from datetime import datetime, timezone
    source = Path(__file__).resolve().parents[1]
    destination = plugin_path(version)
    if destination.exists():
        suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        # Keep old installations outside KiCad's scanned plugins directory to
        # avoid double registration of action plugins.
        backup_dir = destination.parent.parent / "tauvsync-plugin-backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / (destination.name + ".old-" + suffix)
        destination.rename(backup)
        print("Backed up previous plugin to", backup)
    destination.parent.mkdir(parents=True, exist_ok=True)
    copytree(Path(__file__).resolve().parent / "tauvsync_plugin", destination)
    copytree(source / "tauvsync", destination / "tauvsync")
    print("Installed TAUVSYNC into", destination)
    print("Restart PCB Editor, then Tools > External Plugins > TAUVSYNC — Team Projects")
    print("The client requires a separate Python 3 installation with Tkinter.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python client/kicad_plugin/install.py 10.0")
    install(sys.argv[1])
