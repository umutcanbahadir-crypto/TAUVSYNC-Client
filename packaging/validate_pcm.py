"""Check the generated KiCad PCM ZIP against KiCad's published JSON schema.

Run in release CI, not on users' machines.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
from urllib.request import urlopen
from zipfile import ZipFile

SCHEMA_URL = "https://gitlab.com/kicad/code/kicad/-/raw/master/kicad/pcm/schemas/pcm.v2.schema.json"
API_SCHEMA_URL = "https://gitlab.com/kicad/code/kicad/-/raw/master/api/schemas/api.v1.schema.json"


def validate(package: Path) -> None:
    from jsonschema import Draft7Validator

    with urlopen(SCHEMA_URL, timeout=30) as connection:
        schema = json.load(connection)
    with urlopen(API_SCHEMA_URL, timeout=30) as connection:
        api_schema = json.load(connection)

    with ZipFile(package) as archive:
        metadata = json.loads(archive.read("metadata.json"))
        plugin = json.loads(archive.read("plugins/plugin.json"))
        names = set(archive.namelist())

    Draft7Validator.check_schema(schema)
    Draft7Validator.check_schema(api_schema)
    errors = sorted(Draft7Validator(schema).iter_errors(metadata), key=lambda e: list(map(str, e.path)))
    errors += sorted(Draft7Validator(api_schema).iter_errors(plugin), key=lambda e: list(map(str, e.path)))

    for error in errors:
        print(f"Schema violation at {'/'.join(map(str, error.path))}: {error.message}", file=sys.stderr)
    if errors:
        raise SystemExit(f"{len(errors)} KiCad schema validation error(s)")

    exe = "plugins/" + plugin["actions"][0]["entrypoint"]
    if exe not in names:
        raise SystemExit(f"KiCad executable not packaged: {exe}")
    for icon in plugin["actions"][0].get("icons-light", []) + plugin["actions"][0].get("icons-dark", []):
        if "plugins/" + icon not in names:
            raise SystemExit(f"KiCad toolbar icon not packaged: {icon}")

    if metadata["versions"][0].get("runtime") != "ipc":
        raise SystemExit("PCM version runtime must declare ipc")
    print(f"Validated KiCad v2 PCM metadata and IPC manifest: {package}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python packaging/validate_pcm.py PATH_TO_PACKAGE.zip")
    validate(Path(sys.argv[1]))
