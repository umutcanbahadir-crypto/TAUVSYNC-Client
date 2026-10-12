"""Safe, versioned blank KiCad 10 project templates used by TAUV's New Project.

No calls to KiCad, Git, or the shell; create a new ZIP in a temporary directory
and submit it through TAUV's existing authenticated project-creation endpoint.
"""
from __future__ import annotations

from pathlib import Path
import json
import re
import tempfile
import uuid
from zipfile import ZipFile, ZIP_DEFLATED

from .sync import SyncUnsafe

_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = re.compile(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$', re.I)
KINDS = ("both", "schematic", "pcb")


def validate_project_name(name: str) -> str:
    name = name.strip()
    if (not name or len(name) > 80 or name in (".", "..") or
            name.endswith((".", " ")) or _INVALID.search(name) or
            _RESERVED.fullmatch(name) or name.startswith(".")):
        raise ValueError("Choose a project name without Windows special characters (1–80 characters)")
    return name


def blank_schematic() -> str:
    root = str(uuid.uuid4())
    # KiCad 10 compatible minimal sheet with explicit sheet_instances.
    return (
        '(kicad_sch\n'
        '  (version 20250114)\n'
        '  (generator "eeschema")\n'
        '  (generator_version "10.0")\n'
        f'  (uuid "{root}")\n'
        '  (paper "A4")\n'
        '  (lib_symbols)\n'
        '  (sheet_instances (path "/" (page "1")))\n'
        '  (embedded_fonts no)\n'
        ')\n'
    )


def blank_pcb() -> str:
    # Empty KiCad 9/10 PCB S-expression. KiCad will fill in additional
    # design-rule settings when the PCB Editor first saves the board.
    return (
        '(kicad_pcb\n'
        '  (version 20241229)\n'
        '  (generator "pcbnew")\n'
        '  (generator_version "10.0")\n'
        '  (general (thickness 1.6) (legacy_teardrops no))\n'
        '  (paper "A4")\n'
        '  (layers\n'
        '    (0 "F.Cu" signal)\n'
        '    (2 "B.Cu" signal)\n'
        '    (9 "F.Adhes" user "F.Adhesive")\n'
        '    (11 "B.Adhes" user "B.Adhesive")\n'
        '    (13 "F.Paste" user)\n'
        '    (15 "B.Paste" user)\n'
        '    (5 "F.SilkS" user "F.Silkscreen")\n'
        '    (7 "B.SilkS" user "B.Silkscreen")\n'
        '    (1 "F.Mask" user)\n'
        '    (3 "B.Mask" user)\n'
        '    (17 "Dwgs.User" user "User.Drawings")\n'
        '    (19 "Cmts.User" user "User.Comments")\n'
        '    (21 "Eco1.User" user "User.Eco1")\n'
        '    (23 "Eco2.User" user "User.Eco2")\n'
        '    (25 "Edge.Cuts" user)\n'
        '    (27 "Margin" user)\n'
        '    (31 "F.CrtYd" user "F.Courtyard")\n'
        '    (29 "B.CrtYd" user "B.Courtyard")\n'
        '    (35 "F.Fab" user)\n'
        '    (33 "B.Fab" user)\n'
        '  )\n'
        '  (setup (pad_to_mask_clearance 0))\n'
        '  (net 0 "")\n'
        '  (embedded_fonts no)\n'
        ')\n'
    )


def build_blank_archive(name: str, kind: str, target: Path) -> Path:
    name = validate_project_name(name)
    if kind not in KINDS:
        raise ValueError("Unknown KiCad project template")
    target = Path(target)
    if target.exists():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with ZipFile(target, "x", compression=ZIP_DEFLATED) as archive:
            # The project manager writes default settings when first opened.
            archive.writestr(f"{name}.kicad_pro", json.dumps({}) + "\n")
            if kind in ("both", "schematic"):
                archive.writestr(f"{name}.kicad_sch", blank_schematic())
            if kind in ("both", "pcb"):
                archive.writestr(f"{name}.kicad_pcb", blank_pcb())
        return target
    except Exception:
        target.unlink(missing_ok=True)
        raise


def create_cloud_project(api, engine, name: str, kind: str):
    """Create remotely and checkout locally. Local state is not changed on failure.

    A server create may succeed even if checkout later fails; callers must
    refresh the cloud list and offer checkout instead of creating duplicates.
    """
    name = validate_project_name(name)
    with tempfile.TemporaryDirectory(prefix="tauv-new-") as folder:
        zip_path = Path(folder) / "initial.zip"
        build_blank_archive(name, kind, zip_path)
        response = api.create(name, zip_path)
    project = response["project"]
    try:
        managed = engine.checkout(project)
    except Exception as error:
        raise SyncUnsafe(
            "Project was CREATED on the server but local checkout failed. "
            "Refresh the cloud list and open the new project; do not create it again. "
            f"Details: {error}"
        ) from error
    return project, managed
