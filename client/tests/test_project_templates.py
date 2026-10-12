"""No-server tests for TAUV's complete New Project and managed checkout flow."""
from pathlib import Path
import io
import json
import tempfile
import unittest
from zipfile import ZipFile

from client.tauvsync.project_templates import (
    build_blank_archive, create_cloud_project, validate_project_name, KINDS,
)
from client.tauvsync.sync import SyncEngine


class FakeAPI:
    def __init__(self):
        self.calls = []
        self.project = {"id": "a" * 32, "name": "Converter", "head_revision": 1, "cloud_state": "active"}

    def create(self, name, archive):
        self.calls.append(("create", name))
        self.project["name"] = name
        self.blob = Path(archive).read_bytes()
        return {"project": dict(self.project)}

    def download(self, project_id, revision, target):
        self.calls.append(("download", revision))
        Path(target).write_bytes(self.blob)


class ProjectTemplateTests(unittest.TestCase):
    def test_valid_unicode_name_and_reject_unsafe_windows_names(self):
        self.assertEqual(validate_project_name(" Ses Kartı "), "Ses Kartı")
        for bad in ("", ".", "..", "CON", "COM1", "bad/name", r"bad\name",
                    "bad:name", "trailing.", "x" * 81):
            with self.subTest(name=bad), self.assertRaises(ValueError):
                validate_project_name(bad)

    def test_all_templates_are_valid_archive_shapes(self):
        for kind in KINDS:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                target = Path(temp) / "new.zip"
                build_blank_archive("Converter", kind, target)
                with ZipFile(target) as zip_file:
                    names = set(zip_file.namelist())
                    self.assertIn("Converter.kicad_pro", names)
                    self.assertEqual(json.loads(zip_file.read("Converter.kicad_pro")), {})
                    self.assertEqual("Converter.kicad_sch" in names, kind in ("both", "schematic"))
                    self.assertEqual("Converter.kicad_pcb" in names, kind in ("both", "pcb"))
                    if "Converter.kicad_sch" in names:
                        self.assertIn(b"(version 20250114)", zip_file.read("Converter.kicad_sch"))
                        self.assertIn(b"(sheet_instances", zip_file.read("Converter.kicad_sch"))
                    if "Converter.kicad_pcb" in names:
                        self.assertIn(b"(version 20241229)", zip_file.read("Converter.kicad_pcb"))
                with self.assertRaises(FileExistsError):
                    build_blank_archive("Converter", kind, target)

    def test_create_registers_cloud_revision_and_managed_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            api = FakeAPI()
            engine = SyncEngine(api, Path(folder) / "workspace")
            project, path = create_cloud_project(api, engine, "Converter", "both")
            self.assertEqual(project["head_revision"], 1)
            self.assertTrue(path.name.endswith(".kicad_pro"))
            self.assertTrue(path.is_file())
            self.assertTrue(path.with_suffix(".kicad_sch").is_file())
            self.assertTrue(path.with_suffix(".kicad_pcb").is_file())
            self.assertEqual([x[0] for x in api.calls], ["create", "download"])
            self.assertEqual(engine.local_projects()[project["id"]]["base_revision"], 1)

    def test_failed_checkout_does_not_recreate_cloud_project(self):
        with tempfile.TemporaryDirectory() as folder:
            api = FakeAPI()
            engine = SyncEngine(api, Path(folder) / "workspace")
            api.download = lambda *_args: (_ for _ in ()).throw(IOError("network"))
            with self.assertRaisesRegex(Exception, "CREATED on the server"):
                create_cloud_project(api, engine, "Converter", "both")
            self.assertEqual(sum(x[0] == "create" for x in api.calls), 1)
            self.assertEqual(engine.local_projects(), {})


if __name__ == "__main__":
    unittest.main()
