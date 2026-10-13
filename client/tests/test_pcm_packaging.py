"""Offline checks for the self-contained TAUV IPC package."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from client.tauvsync.update_check import APP_VERSION


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("tauv_pcm_builder", ROOT / "packaging" / "build_pcm.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class IPCPackageTests(unittest.TestCase):
    def test_manifest_uses_executable_ipc_runtime(self):
        manifest = json.loads((ROOT / "packaging" / "pcm" / "plugin.json").read_text())
        self.assertEqual(manifest["runtime"]["type"], "exec")
        self.assertEqual(manifest["actions"][0]["scopes"], ["pcb"])
        self.assertEqual(manifest["actions"][0]["entrypoint"], "TAUVSYNC.exe")

    def test_icons_exist_and_are_real_png(self):
        for size in (24, 64):
            icon = ROOT / "client" / "tauvsync" / "resources" / f"tauv_transparent_{size}.png"
            self.assertTrue(icon.is_file())
            self.assertTrue(icon.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))

    def test_pcm_zip_contains_only_supported_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            fake_exe = home / "TAUVSYNC.exe"
            fake_exe.write_bytes(b"MZdummy")
            output = home / "installer.zip"
            builder.build(fake_exe, output)
            with ZipFile(output) as z:
                self.assertEqual(set(z.namelist()), {
                    "metadata.json", "plugins/plugin.json",
                    "plugins/TAUVSYNC.exe", "plugins/tauv_transparent_24.png",
                    "resources/icon.png",
                })
                self.assertEqual(z.read("plugins/TAUVSYNC.exe"), b"MZdummy")
                meta = json.loads(z.read("metadata.json"))
                self.assertEqual(meta["versions"][0]["runtime"], "ipc")
                self.assertEqual(meta["versions"][0]["kicad_version"], "10.0")
                self.assertEqual(meta["versions"][0]["version"], APP_VERSION)
                self.assertEqual(meta["versions"][0]["status"], "testing")
                self.assertEqual(meta["versions"][0]["platforms"], ["windows"])
                self.assertTrue(meta["author"]["contact"]["web"].startswith("https://"))

            self.assertTrue(output.with_suffix(".zip.sha256").is_file())


if __name__ == "__main__":
    unittest.main()
