"""Test live Prism registry reconciliation and already-rendered thumbnails."""
import io
import json
import unittest
from unittest import mock

from client.tauvsync.api import APIError, PrismAPI


class Response(io.BytesIO):
    def __init__(self, content: bytes, mime: str = "application/json"):
        super().__init__(content)
        self.headers = {"Content-Type": mime}


class PrismLiveIndexTests(unittest.TestCase):
    def setUp(self):
        self.api = PrismAPI("https://team.example.test")

    def test_website_deletion_overrides_stale_cloud_state(self):
        cloud = [{"id": "a" * 32, "prism_project_id": "proj_old",
                  "name": "Old", "cloud_state": "active", "head_revision": 2}]
        with mock.patch.object(self.api, "_request", side_effect=[
            Response(json.dumps(cloud).encode()),
            Response(json.dumps([{"id": "proj_other"}]).encode()),
        ]) as request:
            projects = self.api.projects()
        self.assertEqual(projects[0]["cloud_state"], "missing_prism")
        self.assertIn("no-cache", str(request.call_args_list[0]).lower())
        self.assertIn("no-cache", str(request.call_args_list[1]).lower())

    def test_live_registry_keeps_existing_project_active(self):
        cloud = [{"id": "a" * 32, "prism_project_id": "proj_a",
                  "name": "A", "cloud_state": "active"}]
        with mock.patch.object(self.api, "_request", side_effect=[
            Response(json.dumps(cloud).encode()),
            Response(json.dumps([{"id": "proj_a"}]).encode()),
        ]):
            self.assertEqual(self.api.projects()[0]["cloud_state"], "active")

    def test_registry_failure_preserves_last_known_server_state(self):
        cloud = [{"id": "a" * 32, "prism_project_id": "proj_a",
                  "name": "A", "cloud_state": "active"}]
        with mock.patch.object(self.api, "_request", side_effect=[
            Response(json.dumps(cloud).encode()), APIError("unavailable", 503)
        ]):
            self.assertEqual(self.api.projects(), cloud)

    def test_fetches_existing_prism_thumbnail_with_proj_underscore(self):
        with mock.patch.object(self.api, "_request",
                               return_value=Response(b"\x89PNG\r\n", "image/png")) as request:
            raw = self.api.thumbnail("proj_abcd1234")
        self.assertEqual(raw, b"\x89PNG\r\n")
        self.assertEqual(request.call_args.args[0], "/api/projects/proj_abcd1234/thumbnail")

    def test_rejects_malicious_thumbnail_path(self):
        with self.assertRaises(ValueError):
            self.api.thumbnail("../admin")


if __name__ == "__main__":
    unittest.main()
