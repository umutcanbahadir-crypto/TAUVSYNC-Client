"""Build an Ubuntu 22.04 amd64 .deb and a portable tarball from a Linux ELF.

Run only *after* PyInstaller on an ubuntu-22.04 x86_64 runner. Packaging a
Windows .exe or building on newer Ubuntu is not equivalent to Ubuntu 22.04
binary compatibility.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "2.2.1"


def build(executable: Path, out_dir: Path) -> tuple[Path, Path]:
    executable = Path(executable).resolve(strict=True)
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    if executable.read_bytes()[:4] != b"\x7fELF":
        raise ValueError("Expected a Linux ELF, not a Windows executable")
    if not executable.is_file():
        raise ValueError("Expected bundled Linux executable")

    deb = out_dir / f"tauvsync_{VERSION}_amd64.deb"
    bundle = out_dir / f"TAUVSYNC-linux-x86_64-{VERSION}.tar.gz"
    icon = ROOT / "client" / "tauvsync" / "resources" / "tauv_transparent_64.png"
    guide = ROOT / "docs" / "LINUX-UBUNTU22.04.md"
    desktop = """[Desktop Entry]
Type=Application
Name=TAUVSYNC
Comment=TAUV KiCad 10 project collaboration and synchronization
Exec=/usr/bin/tauvsync
Icon=tauvsync
Terminal=false
Categories=Development;Electronics;
StartupNotify=true
"""
    control = f"""Package: tauvsync
Version: {VERSION}
Section: electronics
Priority: optional
Architecture: amd64
Maintainer: TAUV Team <noreply@github.com>
Depends: libc6 (>= 2.35), libsecret-tools, xdg-utils, libx11-6, libxext6, libxft2
Recommends: gnome-keyring
Description: TAUVSYNC desktop client for KiCad 10
 Standalone desktop client for team KiCad 10 projects.
 Sync needs a compatible authenticated TAUVSYNC backend.
"""
    with tempfile.TemporaryDirectory(prefix="tauvsync-package-") as tmp:
        stage = Path(tmp) / "tauvsync"
        (stage / "DEBIAN").mkdir(parents=True)
        (stage / "opt" / "tauvsync").mkdir(parents=True)
        (stage / "usr" / "bin").mkdir(parents=True)
        app_dir = stage / "opt" / "tauvsync"
        target = app_dir / "TAUVSYNC"
        shutil.copyfile(executable, target)
        target.chmod(0o755)
        link = stage / "usr" / "bin" / "tauvsync"
        link.symlink_to("/opt/tauvsync/TAUVSYNC")
        icon_dir = stage / "usr" / "share" / "icons" / "hicolor" / "64x64" / "apps"
        icon_dir.mkdir(parents=True)
        shutil.copyfile(icon, icon_dir / "tauvsync.png")
        desktop_dir = stage / "usr" / "share" / "applications"
        desktop_dir.mkdir(parents=True)
        (desktop_dir / "tauvsync.desktop").write_text(desktop, encoding="utf-8")
        doc = stage / "usr" / "share" / "doc" / "tauvsync"
        doc.mkdir(parents=True)
        shutil.copyfile(guide, doc / "README-linux.md")
        (stage / "DEBIAN" / "control").write_text(control, encoding="utf-8")
        subprocess.run(["dpkg-deb", "--build", "--root-owner-group",
                        str(stage), str(deb)], check=True)

    # Portable ELF bundle: requires the host's graphical/Secret Service deps.
    # The .deb is recommended for reliable desktop integration.
    with tempfile.TemporaryDirectory(prefix="tauvsync-tar-") as tmp:
        root = Path(tmp) / "TAUVSYNC-linux-x86_64"
        root.mkdir()
        binary = root / "TAUVSYNC"
        shutil.copyfile(executable, binary)
        binary.chmod(0o755)
        shutil.copyfile(guide, root / "README-linux.md")
        with tarfile.open(bundle, "w:gz") as archive:
            archive.add(root, arcname=root.name)
    for artifact in (deb, bundle):
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        (out_dir / (artifact.name + ".sha256")).write_text(
            f"{digest}  {artifact.name}\n", encoding="ascii")
    return deb, bundle


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, default=ROOT / "dist" / "TAUVSYNC")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    for output in build(args.exe, args.output_dir):
        print("Built", output)
