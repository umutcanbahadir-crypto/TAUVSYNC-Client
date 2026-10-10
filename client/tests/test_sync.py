import io
from pathlib import Path
import stat
import tempfile
import unittest
from zipfile import ZipFile, ZipInfo

from client.tauvsync.api import PrismAPI
from client.tauvsync.sync import (
    SyncEngine, SyncUnsafe, ignored, package_project, safe_extract,
)


class FakeAPI:
    def __init__(self):
        self.id = "a" * 32
        self.history = {1: "original"}
        self.head = 1
        self.uploads = []

    def project(self):
        return {"id": self.id, "name": "Underwater Modem", "head_revision": self.head}

    def download(self, pid, rev, path):
        assert pid == self.id
        with ZipFile(path, "x") as z:
            z.writestr("Modem/Modem.kicad_pro", "{}")
            z.writestr("Modem/Modem.kicad_sch", self.history[rev])
            z.writestr("Modem/Modem.kicad_prl", "ephemeral-local-preferences")

    def publish(self, pid, base, archive):
        assert pid == self.id
        with ZipFile(archive) as z:
            self.uploads.append((base, z.namelist()))
            value = z.read("Modem/Modem.kicad_sch").decode()
            assert not any(n.endswith(".kicad_prl") for n in z.namelist())
        revision = max(self.history) + 1
        self.history[revision] = value
        status = "current" if base == self.head else "alternate"
        if status == "current":
            self.head = revision
        return {"number": revision, "status": status}

    def remote_update(self, value):
        revision = max(self.history) + 1
        self.history[revision] = value
        self.head = revision
        return revision


class SyncEngineTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.api = FakeAPI()
        self.current_time = 0
        self.engine = SyncEngine(
            self.api, self.root / "workspace",
            settle_seconds=8, clock=lambda: self.current_time,
        )
        self.pro = self.engine.checkout(self.api.project())
        self.schematic = self.pro.with_suffix(".kicad_sch")

    def test_checkout_into_local_folder(self):
        self.assertTrue(self.pro.exists())
        self.assertEqual(self.schematic.read_text(), "original")
        self.assertEqual(self.engine._record(self.api.id)["base_revision"], 1)

    def test_automatic_upload_after_quiet_period(self):
        self.schematic.write_text("saved changes")
        self.assertIn("Waiting", self.engine.poll(
            self.api.id, self.api.project(), editors_open=True
        ))
        self.current_time += 9
        self.assertEqual(self.engine.poll(
            self.api.id, self.api.project(), editors_open=True
        ), "Published r2")
        self.assertEqual(self.api.history[2], "saved changes")
        self.assertEqual(self.engine._record(self.api.id)["base_revision"], 2)
        self.assertEqual(len(self.api.uploads), 1)

    def test_remote_update_downloads_and_waits_for_editor(self):
        self.api.remote_update("teammate changes")
        result = self.engine.poll(self.api.id, self.api.project(), editors_open=True)
        self.assertIn("waiting for KiCad editors to close", result)
        self.assertEqual(self.schematic.read_text(), "original")
        self.assertEqual(self.engine._record(self.api.id)["base_revision"], 1)
        result = self.engine.poll(self.api.id, self.api.project(), editors_open=False)
        self.assertIn("Auto-updated", result)
        self.assertEqual(self.schematic.read_text(), "teammate changes")
        self.assertEqual(self.engine._record(self.api.id)["base_revision"], 2)
        backups = list(self.engine.backups.iterdir())
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / "Modem/Modem.kicad_sch").read_text(), "original")

    def test_remote_and_local_changes_do_not_overwrite_each_other(self):
        self.schematic.write_text("my unsent work")
        self.api.remote_update("teammate work")
        message = self.engine.poll(self.api.id, self.api.project(), editors_open=False)
        self.assertIn("Conflict", message)
        self.assertEqual(self.schematic.read_text(), "my unsent work")
        self.assertEqual(self.engine._record(self.api.id)["base_revision"], 1)
        self.assertEqual(self.api.head, 2)
        self.assertTrue(self.engine._record(self.api.id)["conflict"])
        self.assertEqual(len(self.api.uploads), 0)

    def test_conflict_preserve_as_alternate_then_explicit_safe_pull(self):
        self.schematic.write_text("my work")
        self.api.remote_update("theirs")
        self.engine.poll(self.api.id, self.api.project(), editors_open=False)
        alternate = self.engine.preserve_local_on_server(self.api.id)
        self.assertEqual(alternate["status"], "alternate")
        self.assertEqual(self.api.history[3], "my work")
        self.assertEqual(self.api.head, 2)
        with self.assertRaises(SyncUnsafe):
            self.engine.resolve_use_server(self.api.id, self.api.project(), editors_open=True)
        self.engine.resolve_use_server(self.api.id, self.api.project(), editors_open=False)
        self.assertEqual(self.schematic.read_text(), "theirs")
        self.assertEqual(self.engine._record(self.api.id)["base_revision"], 2)
        backups = list(self.engine.backups.iterdir())
        self.assertEqual((backups[0] / "Modem/Modem.kicad_sch").read_text(), "my work")

    def test_offline_publish_retains_local_changes(self):
        class Offline(Exception):
            pass
        self.schematic.write_text("unpublished")
        self.engine.poll(self.api.id, self.api.project(), editors_open=True)
        self.current_time += 10
        def outage(*args):
            raise Offline("Server not reachable")
        self.api.publish = outage
        with self.assertRaises(Offline):
            self.engine.poll(self.api.id, self.api.project(), editors_open=False)
        self.assertEqual(self.schematic.read_text(), "unpublished")
        self.assertEqual(self.engine._record(self.api.id)["base_revision"], 1)

    def test_session_restart_preserves_revision_and_hashes(self):
        new = SyncEngine(self.api, self.root / "workspace")
        self.assertEqual(new._record(self.api.id)["base_revision"], 1)
        self.assertEqual(new.folder(self.api.id), self.pro.parent.parent)

    def test_local_preferences_not_uploaded(self):
        ephemeral = self.pro.with_suffix(".kicad_prl")
        ephemeral.write_text("preferences")
        self.engine.poll(self.api.id, self.api.project(), editors_open=False)
        self.assertEqual(self.api.uploads, [])
        self.assertTrue(ignored(ephemeral.name))

    def test_symlink_rejected_during_scanning(self):
        try:
            (self.pro.parent / "secret.txt").symlink_to(self.pro)
        except (OSError, NotImplementedError):
            self.skipTest("Platform symlinks not available")
        with self.assertRaises(SyncUnsafe):
            self.engine.poll(self.api.id, self.api.project(), editors_open=False)


class ArchiveSafetyTests(unittest.TestCase):
    def test_zip_slip_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "a.zip"
            with ZipFile(archive, "w") as z:
                z.writestr("Modem/Modem.kicad_pro", "{}")
                z.writestr("../outside.txt", "PWN")
            with self.assertRaises(SyncUnsafe):
                safe_extract(archive, root / "files")
            self.assertFalse((root / "outside.txt").exists())

    def test_zip_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "b.zip"
            link = ZipInfo("Modem/external")
            link.create_system = 3
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            with ZipFile(archive, "w") as z:
                z.writestr("Modem/Modem.kicad_pro", "{}")
                z.writestr(link, "../../secret")
            with self.assertRaises(SyncUnsafe):
                safe_extract(archive, root / "files")


class APIValidationTests(unittest.TestCase):
    def test_https_is_required_except_loopback(self):
        with self.assertRaises(ValueError):
            PrismAPI("http://example.com")
        self.assertEqual(PrismAPI("https://example.com").base, "https://example.com")
        self.assertEqual(PrismAPI("http://localhost:8080").base, "http://localhost:8080")

    def test_no_credentials_inside_url(self):
        with self.assertRaises(ValueError):
            PrismAPI("https://user:password@example.com")


if __name__ == "__main__":
    unittest.main()
