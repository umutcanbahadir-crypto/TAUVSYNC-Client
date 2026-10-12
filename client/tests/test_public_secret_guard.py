"""Validate that public-client CI rejects credentials without storing real ones."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "check_public_secrets.py"
spec = importlib.util.spec_from_file_location("tauv_guard", MODULE_PATH)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class PublicClientSecretGuardTests(unittest.TestCase):
    def test_rejects_personal_sign_up_email(self):
        personal_email = ("demo@" + "gmail.com").encode()
        self.assertIn("personal email address",
                      guard.inspect_file("example.py", personal_email))

    def test_rejects_access_token_or_private_key(self):
        example_token = ("ghp_" + "A" * 36).encode()
        self.assertIn("GitHub access token",
                      guard.inspect_file("example.py", example_token))
        fake_key_header = ("-----BEGIN " + "PRIVATE KEY-----").encode()
        self.assertIn("private key", guard.inspect_file("example.py", fake_key_header))

    def test_rejects_private_environment_files(self):
        self.assertTrue(guard.inspect_file(".env", b""))
        self.assertTrue(guard.inspect_file("login.dpapi", b"\0"))

    def test_allows_reserved_test_fixture_urls(self):
        example = ("https://name:fake@" + "example.com").encode()
        self.assertEqual(guard.inspect_file("test.py", example), [])

    def test_rejects_real_domains_with_url_credentials(self):
        example = ("https://name:fake@" + "production.invalid-domain.test").encode()
        self.assertIn("embedded URL credentials",
                      guard.inspect_file("code.py", example))


if __name__ == "__main__":
    unittest.main()
