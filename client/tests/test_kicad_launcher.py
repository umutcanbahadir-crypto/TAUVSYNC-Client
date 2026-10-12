"""Windows KiCad 10 launch regression tests (no real KiCad installation needed)."""
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from client.tauvsync.kicad_launcher import find_kicad10, launch_kicad_project


class KiCad10LauncherTests(unittest.TestCase):
    def test_detects_kicad10_even_when_windows_associates_projects_to_kicad9(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "Program Files"
            exe = root / "KiCad" / "10.0" / "bin" / "kicad.exe"
            exe.parent.mkdir(parents=True)
            exe.write_bytes(b"MZ")
            old = root / "KiCad" / "9.0" / "bin" / "kicad.exe"
            old.parent.mkdir(parents=True)
            old.write_bytes(b"MZ")
            self.assertEqual(find_kicad10(environ={"ProgramFiles": str(root)}), exe)

            project = Path(folder) / "design.kicad_pro"
            project.write_text("{}")
            with mock.patch("client.tauvsync.kicad_launcher.subprocess.Popen") as popen:
                launch_kicad_project(project, platform="win32",
                                     environ={"ProgramFiles": str(root)})
            self.assertEqual(popen.call_args.args[0], [str(exe), str(project)])
            self.assertNotIn(str(old), popen.call_args.args[0])
            self.assertEqual(popen.call_args.kwargs.get("creationflags", 0) & 0x08000000,
                             0x08000000)

    def test_override_supports_nonstandard_kicad10_installations(self):
        with tempfile.TemporaryDirectory() as folder:
            exe = Path(folder) / "kicad.exe"
            exe.write_bytes(b"MZ")
            self.assertEqual(find_kicad10(environ={"TAUV_KICAD10_EXE": str(exe)}), exe)

    def test_missing_kicad10_fails_instead_of_opening_kicad9(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(FileNotFoundError, "KiCad 10"):
                find_kicad10(environ={"ProgramFiles": folder})


if __name__ == "__main__":
    unittest.main()
