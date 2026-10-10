"""Tests for current-project upload and secure opt-in Windows login."""
from __future__ import annotations

from pathlib import Path
from unittest import mock
import io
import json
import sys
import tempfile
import unittest
from zipfile import ZipFile

from client.tauvsync import credentials
from client.tauvsync.api import PrismAPI
from client.tauvsync.app import find_project_file
from client.tauvsync.sync import SyncEngine


class APIProjectCreateTests(unittest.TestCase):
    def test_create_streams_full_project_archive(self):
        with tempfile.TemporaryDirectory() as home:
            archive = Path(home) / "board.zip"
            with ZipFile(archive, "w") as z:
                z.writestr("Board.kicad_pro", "{}")
                z.writestr("Board.kicad_pcb", "(kicad_pcb)")
            api = PrismAPI("http://127.0.0.1:18080")
            def fake_request(path, *, method, data, headers):
                self.assertEqual(path, "/api/tauvsync/projects")
                self.assertEqual(method, "POST")
                body = b"".join(data)
                self.assertEqual(len(body), int(headers["Content-Length"]))
                self.assertIn(b'name="name"\r\n\r\nModem', body)
                self.assertIn(archive.read_bytes(), body)
                return io.BytesIO(b'{"project":{"id":"abc"}}')
            with mock.patch.object(api, "_request", side_effect=fake_request):
                result = api.create("Modem", archive)
            self.assertEqual(result["project"]["id"], "abc")


class LocalUploadTests(unittest.TestCase):
    class FakeAPI:
        def create(self, name, archive):
            self.uploaded = archive.read_bytes()
            return {"project": {"id": "a" * 32, "name": name, "head_revision": 1}}

        def download(self, pid, revision, path):
            path.write_bytes(self.uploaded)

        def publish(self, pid, base, archive):
            self.published = archive.read_bytes()
            return {"number": 2, "status": "current"}

    def test_current_board_to_cloud_managed_copy_without_touching_original(self):
        with tempfile.TemporaryDirectory() as home:
            root = Path(home)
            source = root / "original"
            source.mkdir()
            board = source / "Test.kicad_pcb"
            board.write_text("(kicad_pcb)")
            project = source / "Test.kicad_pro"
            project.write_text("{}")
            (source / "Test.kicad_sch").write_text("schematic")
            (source / "Test.kicad_prl").write_text("not for sharing")
            self.assertEqual(find_project_file(board), project.resolve())
            api = self.FakeAPI()
            engine = SyncEngine(api, root / "workspace", settle_seconds=0)
            uploaded, managed = engine.upload_local_project(project, "Test")
            self.assertEqual(uploaded["id"], "a" * 32)
            self.assertNotEqual(managed.resolve(), project.resolve())
            self.assertEqual(project.read_text(), "{}")
            self.assertTrue(managed.is_file())
            self.assertFalse((managed.parent / "Test.kicad_prl").exists())
            (managed.parent / "Test.kicad_sch").write_text("new schematic")
            message = engine.poll(uploaded["id"], uploaded, editors_open=True)
            self.assertEqual(message, "Published r2")
            with ZipFile(io.BytesIO(api.published)) as archive:
                self.assertEqual(archive.read("Test.kicad_sch"), b"new schematic")
            self.assertEqual((source / "Test.kicad_sch").read_text(), "schematic")


class CredentialTests(unittest.TestCase):
    def test_password_never_in_preferences_and_login_store_is_opt_in(self):
        with tempfile.TemporaryDirectory() as home:
            with mock.patch.object(credentials, "CREDENTIALS", Path(home) / "login.dpapi"):
                def fake_protect(data, *, decrypt=False):
                    return data[::-1]
                with mock.patch.object(credentials, "_protect", side_effect=fake_protect):
                    credentials.store_login("https://sync.example.test", "user@example.test", "top-secret")
                    self.assertNotIn(b"top-secret", credentials.CREDENTIALS.read_bytes())
                    self.assertEqual(credentials.load_login(
                        "https://sync.example.test", "user@example.test"), "top-secret")
                    self.assertIsNone(credentials.load_login(
                        "https://other.example.test", "user@example.test"))
                    credentials.forget_login()
                    self.assertIsNone(credentials.load_login(
                        "https://sync.example.test", "user@example.test"))

    @unittest.skipUnless(sys.platform == "win32", "Windows DPAPI is Windows-only")
    def test_windows_dpapi_roundtrip(self):
        with tempfile.TemporaryDirectory() as home:
            with mock.patch.object(credentials, "CREDENTIALS", Path(home) / "login.dpapi"):
                credentials.store_login("https://sync.example.test", "admin@test.test", "some-password")
                self.assertEqual(credentials.load_login(
                    "https://sync.example.test", "admin@test.test"), "some-password")


if __name__ == "__main__":
    unittest.main()
