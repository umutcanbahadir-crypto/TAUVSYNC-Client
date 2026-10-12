"""Upgrade-safety and TAUV-only user configuration regression tests."""
from pathlib import Path
from unittest import mock
import json
import tempfile
import unittest

from client.tauvsync import app
from client.tauvsync.api import PrismAPI


class TAUVClientUpgradeTests(unittest.TestCase):
    def test_new_default_server_is_https(self):
        self.assertTrue(app.DEFAULT_SERVER.startswith("https://"))
        self.assertIn("tauvsync-gateway.", app.DEFAULT_SERVER)

    def test_legacy_ssh_config_is_removed_when_saving_settings(self):
        with tempfile.TemporaryDirectory() as temp:
            settings = Path(temp) / "client.json"
            settings.write_text(json.dumps({
                "url": "https://team.example.test",
                "email": "team@example.test",
                "workspace": "C:/TAUVSYNC",
                "remember": True,
                "ssh": {"enabled": True, "key": "C:/secrets/id_ed25519"},
            }))
            with mock.patch.object(app, "SETTINGS", settings):
                old = app.load_preferences()
                self.assertTrue(old["ssh"]["enabled"])
                app.save_preferences(
                    old["url"], old["workspace"], old["email"], old["remember"])
                new = app.load_preferences()
            self.assertNotIn("ssh", new)
            self.assertNotIn("password", new)
            self.assertEqual(new["workspace"], old["workspace"])

    def test_restore_uses_existing_versioned_backend_route(self):
        api = PrismAPI("https://team.example.test")
        project_id = "a" * 32
        with mock.patch.object(api, "_json", return_value={"number": 4}) as call:
            result = api.restore(project_id, 2)
        self.assertEqual(result["number"], 4)
        call.assert_called_once_with(
            f"/api/tauvsync/projects/{project_id}/revisions/2/restore",
            method="POST", payload={})


if __name__ == "__main__":
    unittest.main()
