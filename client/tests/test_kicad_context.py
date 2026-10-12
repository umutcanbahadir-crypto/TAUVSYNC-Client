"""Tests for optional KiCad IPC current-project discovery."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest import mock
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "client"))
spec = importlib.util.spec_from_file_location("tauv_launcher", ROOT / "client" / "launcher.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class KiCadContextTests(unittest.TestCase):
    def test_no_api_socket_falls_back_to_file_picker(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(launcher.current_project_from_kicad())

    def test_open_kicad_project_is_detected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            project = path / "Test.kicad_pro"
            project.write_text("{}", encoding="utf-8")
            fake_project = SimpleNamespace(path=str(path), name="Test")
            board = SimpleNamespace(get_project=lambda: fake_project,
                                    name=str(path / "Test.kicad_pcb"))
            fake_kipy = SimpleNamespace(KiCad=lambda: SimpleNamespace(get_board=lambda: board))
            with mock.patch.dict(sys.modules, {"kipy": fake_kipy}):
                with mock.patch.dict(os.environ, {"KICAD_API_SOCKET": "ipc-test"}, clear=False):
                    self.assertEqual(launcher.current_project_from_kicad(), project.resolve())

    def test_kicad_api_failure_keeps_dashboard_available(self):
        fake_kipy = SimpleNamespace(KiCad=lambda: (_ for _ in ()).throw(RuntimeError("IPC offline")))
        with mock.patch.dict(sys.modules, {"kipy": fake_kipy}):
            with mock.patch.dict(os.environ, {"KICAD_API_SOCKET": "ipc-test"}, clear=False):
                self.assertIsNone(launcher.current_project_from_kicad())


if __name__ == "__main__":
    unittest.main()
