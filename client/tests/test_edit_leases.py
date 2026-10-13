"""Client edit-lock contract: token secrecy, renewal, failure and API methods."""
import unittest
from unittest import mock

from client.tauvsync.api import APIError, PrismAPI


class ExclusiveEditClientTests(unittest.TestCase):
    def setUp(self):
        self.api = PrismAPI("https://example.test")
        self.pid = "a" * 32
        self.token = "token-" + "a" * 48

    def test_open_acquires_single_lease_and_renew_uses_original_token(self):
        with mock.patch.object(self.api, "_json", side_effect=[
            {"token": self.token, "owner": "alice@example.test", "expires_at": 1000},
            {"owner": "alice@example.test", "expires_at": 1030},
        ]) as req:
            self.api.acquire_edit_lock(self.pid)
            self.assertTrue(self.api.has_edit_lock(self.pid))
            self.api.acquire_edit_lock(self.pid)  # Same window renews, not reacquires
        self.assertEqual(req.call_count, 2)
        self.assertEqual(req.call_args.kwargs["payload"], {"token": self.token})
        self.assertEqual(req.call_args.kwargs["method"], "POST")

    def test_conflict_and_stale_token_fail_closed(self):
        with mock.patch.object(self.api, "_json", side_effect=APIError("Locked by Bob", 423)):
            with self.assertRaises(APIError):
                self.api.acquire_edit_lock(self.pid)
        self.assertFalse(self.api.has_edit_lock(self.pid))
        self.api.edit_tokens[self.pid] = self.token
        with mock.patch.object(self.api, "_json", side_effect=APIError("Expired", 409)):
            with self.assertRaises(APIError):
                self.api.renew_edit_lock(self.pid)
        self.assertFalse(self.api.has_edit_lock(self.pid))

    def test_release_clears_token_and_sends_authorized_delete(self):
        self.api.edit_tokens[self.pid] = self.token
        with mock.patch.object(self.api, "_json", return_value={"released": True}) as req:
            self.api.release_edit_lock(self.pid)
        self.assertEqual(req.call_args.kwargs,
                         {"method": "DELETE", "payload": {"token": self.token}})
        self.assertFalse(self.api.has_edit_lock(self.pid))

    def test_no_lock_cannot_publish_without_touching_files(self):
        with mock.patch.object(self.api, "_request") as request:
            with self.assertRaises(APIError) as error:
                self.api.publish(self.pid, 1, "fake.zip")
            self.assertEqual(error.exception.status, 423)
        request.assert_not_called()

    def test_administrator_force_unlock_clears_stale_local_token(self):
        self.api.edit_tokens[self.pid] = self.token
        with mock.patch.object(self.api, "_json", return_value={"released": True}) as request:
            self.api.force_release_edit_lock(self.pid)
        self.assertFalse(self.api.has_edit_lock(self.pid))
        request.assert_called_once_with(
            f"/api/tauvsync/projects/{self.pid}/edit-lock/force",
            method="DELETE", payload={},
        )

    def test_restore_requires_token(self):
        self.api.edit_tokens[self.pid] = self.token
        with mock.patch.object(self.api, "_json", return_value={"number": 4}) as req:
            self.api.restore(self.pid, 2)
        req.assert_called_once_with(
            f"/api/tauvsync/projects/{self.pid}/revisions/2/restore",
            method="POST", payload={"edit_token": self.token},
        )


if __name__ == "__main__":
    unittest.main()
