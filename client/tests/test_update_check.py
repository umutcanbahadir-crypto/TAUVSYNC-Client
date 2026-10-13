"""GitHub release update checks must be safe, versioned, and offline-tolerant."""
import io
import json
import unittest
from unittest import mock
from urllib.error import URLError

from client.tauvsync.update_check import (
    APP_VERSION, AvailableUpdate, RELEASES_API, check_for_update,
    select_update, version_key,
)


def release(tag, *, draft=False, exe=True):
    return {
        "tag_name": tag,
        "draft": draft,
        "prerelease": True,
        "assets": [{"name": "TAUVSYNC.exe"}] if exe else [{"name": "README.txt"}],
    }


class UpdateCheckTests(unittest.TestCase):
    def test_installed_version_and_numeric_order(self):
        self.assertEqual(APP_VERSION, "2.2.1")
        self.assertLess(version_key("v2.9.0"), version_key("v2.10.0"))
        self.assertLess(version_key("2.3.0-beta.1"), version_key("2.3.0"))
        self.assertGreater(version_key("v2.3.0-beta.2"), version_key("2.2.1"))
        self.assertIsNone(version_key("../unsafe"))

    def test_selects_newest_supported_beta_or_stable(self):
        result = select_update([
            release("v2.4.0", draft=True),
            release("v2.3.0", exe=False),
            release("v2.3.0-beta.1"),
            release("v2.2.9"),
            release("v2.3.0-beta.2"),
        ])
        self.assertEqual(result, AvailableUpdate(
            version="2.3.0-beta.2",
            release_url="https://github.com/umutcanbahadir-crypto/TAUVSYNC-Client/releases/tag/v2.3.0-beta.2",
        ))

    def test_never_notifies_for_old_draft_or_missing_executable(self):
        self.assertIsNone(select_update([
            release("v2.2.0"), release("v99.0.0", draft=True),
            release("v5.0.0", exe=False),
        ]))

    def test_fetches_public_releases_instead_of_stable_only_latest(self):
        data = json.dumps([release("v2.2.2")]).encode("utf-8")
        with mock.patch("client.tauvsync.update_check.urlopen", return_value=io.BytesIO(data)) as call:
            update = check_for_update()
        self.assertEqual(update.version, "2.2.2")
        self.assertEqual(call.call_args.kwargs["timeout"], 4.0)
        self.assertEqual(call.call_args.args[0].full_url, RELEASES_API)
        self.assertIn("/releases?per_page=", RELEASES_API)

    def test_offline_rate_limit_and_malformed_json_fail_silently(self):
        with mock.patch("client.tauvsync.update_check.urlopen", side_effect=URLError("offline")):
            self.assertIsNone(check_for_update())
        with mock.patch("client.tauvsync.update_check.urlopen", return_value=io.BytesIO(b"bad json")):
            self.assertIsNone(check_for_update())
        with mock.patch("client.tauvsync.update_check.urlopen", return_value=io.BytesIO(b"{}")):
            self.assertIsNone(check_for_update())


if __name__ == "__main__":
    unittest.main()
