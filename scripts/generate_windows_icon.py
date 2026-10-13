"""Build TAUV's multi-resolution Windows ICO from its transparent PNG source.

The ICO is generated during the Windows build before PyInstaller runs and
is included as a resource in the frozen EXE. Windows users need no Pillow.
"""
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
RESOURCES = ROOT / "client" / "tauvsync" / "resources"
SOURCE = RESOURCES / "tauv_transparent_64.png"
TARGET = RESOURCES / "tauv_app.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def build() -> Path:
    with Image.open(SOURCE) as source:
        img = source.convert("RGBA")
        if img.getpixel((0, 0))[3] != 0:
            raise ValueError("TAUV logo must have a transparent background")
        # Resize to 256 first so Pillow creates each Windows icon resolution.
        large = img.resize((256, 256), Image.Resampling.LANCZOS)
        large.save(TARGET, format="ICO", sizes=[(s, s) for s in SIZES])
    if TARGET.stat().st_size < 1024:
        raise ValueError("TAUV Windows icon is unexpectedly small")
    return TARGET


if __name__ == "__main__":
    print("Generated", build())
