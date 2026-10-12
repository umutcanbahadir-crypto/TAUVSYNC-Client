"""Make a KiCad 10 PCM install-from-file ZIP from a frozen Windows client.

Run after the PyInstaller Windows build. No Python runtime is required on
the machine installing the resulting ZIP; the executable is self-contained.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
NAME = "TAUVSYNC"
VERSION = "2.1.1"


def metadata() -> dict:
    return {
        "$schema": "https://go.kicad.org/pcm/schemas/v2",
        "name": "TAUV — Team Projects",
        "description": "Shared KiCad projects, automatic synchronization and conflict protection.",
        "description_full": (
            "TAUV Team Projects securely connects KiCad 10 to a TAUVSYNC team "
            "server. Windows desktop client; use the PCB Editor external "
            "plugins action. No standalone Python installation required."
        ),
        "identifier": "com.github.umutcanbahadir-crypto.tauvsync",
        "type": "plugin",
        "author": {
            "name": "TAUV",
            "contact": {"web": "https://github.com/umutcanbahadir-crypto/TAUVSYNC-Client"},
        },
        # A public repository without a declared license is NOT assumed MIT.
        # This third-party testing package is not submitted to KiCad's official repository.
        "license": "Proprietary",
        "resources": {
            "homepage": "https://github.com/umutcanbahadir-crypto/TAUVSYNC-Client"
        },
        "versions": [{
            "version": VERSION,
            "status": "testing",
            "kicad_version": "10.0",
            "kicad_version_max": "10.0",
            "platforms": ["windows"],
            "runtime": "ipc",
        }],
    }


def build(executable: Path, output: Path) -> Path:
    executable = Path(executable)
    if not executable.is_file() or executable.suffix.lower() != ".exe":
        raise FileNotFoundError("Expected bundled Windows TAUVSYNC.exe")
    manifest = ROOT / "packaging" / "pcm" / "plugin.json"
    icon24 = ROOT / "client" / "tauvsync" / "resources" / "tauv_icon_24.png"
    icon64 = ROOT / "client" / "tauvsync" / "resources" / "tauv_icon_64.png"
    plugin = json.loads(manifest.read_text(encoding="utf-8"))
    info = metadata()
    if plugin["runtime"]["type"] != "exec":
        raise ValueError("Expected self-contained executable IPC plugin")
    if plugin["actions"][0]["entrypoint"] != "TAUVSYNC.exe":
        raise ValueError("Manifest entrypoint doesn't match bundled executable")
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=9) as package:
        package.writestr("metadata.json", json.dumps(info, indent=2) + "\n")
        package.write(manifest, "plugins/plugin.json")
        package.write(executable, "plugins/TAUVSYNC.exe")
        package.write(icon24, "plugins/tauv_icon_24.png")
        package.write(icon64, "resources/icon.png")
    with ZipFile(output) as package:
        names = set(package.namelist())
        expected = {"metadata.json", "plugins/plugin.json",
                    "plugins/TAUVSYNC.exe", "plugins/tauv_icon_24.png", "resources/icon.png"}
        if names != expected or package.testzip() is not None:
            raise ValueError("Invalid KiCad PCM archive")
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix + ".sha256").write_text(
        f"{digest}  {output.name}\n", encoding="ascii")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, default=ROOT / "dist" / "TAUVSYNC.exe")
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / f"TAUVSYNC-KiCad10-{VERSION}.zip")
    args = parser.parse_args()
    print("Built", build(args.exe, args.output))
