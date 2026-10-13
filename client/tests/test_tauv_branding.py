"""Headless TAUV logo and dedicated-sync-badge regression tests."""
from pathlib import Path
import struct
import zlib
import unittest

from client.tauvsync.workspace_data import synced_status_label

ROOT = Path(__file__).resolve().parents[2] / "client" / "tauvsync" / "resources"


class BrandTests(unittest.TestCase):
    def test_synced_revision_gets_green_badge(self):
        self.assertEqual(synced_status_label("Synced r3"), "Synced r3")
        self.assertEqual(synced_status_label("  Synced r21  "), "Synced r21")
        for value in ("Uploading", "Conflict", "Synced", "Synced r3\nDownloading", None, ""):
            with self.subTest(value=value):
                self.assertIsNone(synced_status_label(value))

    def test_logo_is_transparent_rgba_png(self):
        for size in (24, 64):
            with self.subTest(size=size):
                data = (ROOT / f"tauv_transparent_{size}.png").read_bytes()
                self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
                self.assertEqual(struct.unpack(">II", data[16:24]), (size, size))
                self.assertEqual(data[25], 6)  # PNG RGBA
                position, compressed = 8, []
                found_end = False
                while position < len(data):
                    chunk_length = struct.unpack(">I", data[position:position + 4])[0]
                    tag = data[position + 4:position + 8]
                    payload = data[position + 8:position + 8 + chunk_length]
                    checksum = struct.unpack(">I", data[position + 8 + chunk_length:position + 12 + chunk_length])[0]
                    self.assertEqual(zlib.crc32(tag + payload), checksum)
                    if tag == b"IDAT":
                        compressed.append(payload)
                    if tag == b"IEND":
                        found_end = True
                    position += 12 + chunk_length
                self.assertTrue(found_end)
                self.assertEqual(position, len(data))
                # Every RGBA 8-bit PNG scanline contains a filter byte and 4*size pixels.
                decoded = zlib.decompress(b"".join(compressed))
                self.assertEqual(len(decoded), size * (1 + 4 * size))


if __name__ == "__main__":
    unittest.main()
