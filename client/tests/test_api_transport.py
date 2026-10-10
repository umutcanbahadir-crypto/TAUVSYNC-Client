"""Loopback HTTP integration tests for cookies and streaming multipart uploads.

No external server, secrets, or network access required.
"""
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from client.tauvsync.api import PrismAPI


class Handler(BaseHTTPRequestHandler):
    seen_cookie = False
    seen_upload = False

    def log_message(self, *args):
        pass

    def do_POST(self):
        amount = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(amount)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        if self.path == "/api/auth/login/password":
            payload = json.loads(body)
            assert payload["email"] == "team@example.com"
            self.send_header("Set-Cookie", "prism_session=test-only; HttpOnly; Path=/")
            data = {"email": "team@example.com", "role": "designer", "must_change_password": False}
        elif self.path.endswith("/revisions"):
            self.server.seen_cookie = "prism_session=test-only" in self.headers.get("Cookie", "")
            assert self.headers.get("Content-Type", "").startswith("multipart/form-data; boundary=tauvsync-")
            assert b'name="base_revision"\r\n\r\n4\r\n' in body
            assert b'filename="project.zip"' in body
            assert b"project-binary-content" in body
            self.server.seen_upload = True
            data = {"number": 5, "status": "current"}
        else:
            data = {}
        blob = json.dumps(data).encode()
        self.send_header("Content-Length", str(len(blob)))
        self.end_headers()
        self.wfile.write(blob)

    def do_GET(self):
        self.server.seen_cookie = "prism_session=test-only" in self.headers.get("Cookie", "")
        if self.path.endswith("/download"):
            blob = b"ZIP_DATA"
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
        else:
            blob = b"[]"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(blob)))
        self.end_headers()
        self.wfile.write(blob)


class ApiTransportTests(unittest.TestCase):
    def test_login_cookie_project_list_and_streamed_upload(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.seen_cookie = False
        server.seen_upload = False
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            api = PrismAPI(f"http://127.0.0.1:{server.server_port}")
            self.assertEqual(api.login("team@example.com", "fake-for-test")["role"], "designer")
            self.assertEqual(api.projects(), [])
            self.assertTrue(server.seen_cookie)
            with tempfile.TemporaryDirectory() as directory:
                archive = Path(directory) / "test.zip"
                archive.write_bytes(b"project-binary-content")
                outcome = api.publish("a" * 32, 4, archive)
                self.assertEqual(outcome, {"number": 5, "status": "current"})
                self.assertTrue(server.seen_upload)
                local = Path(directory) / "download.zip"
                api.download("a" * 32, 5, local)
                self.assertEqual(local.read_bytes(), b"ZIP_DATA")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
