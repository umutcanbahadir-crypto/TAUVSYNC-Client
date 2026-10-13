"""HTTPS client for Prism's invitation-only TAUVSYNC API.

Cookies and passwords are kept ONLY in memory. The server validates the user's
existing Prism account, so this client doesn't create a new credential system.
"""
from __future__ import annotations

import http.cookiejar
import json
from pathlib import Path
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
import uuid


class APIError(RuntimeError):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


class PrismAPI:
    def __init__(self, base_url: str, *, timeout: int = 45):
        parsed = urllib.parse.urlsplit(base_url.rstrip("/"))
        if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
            raise ValueError("Enter the server's HTTPS origin, e.g. https://sync.example.com")
        if parsed.scheme != "https" and not (
            parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost", "::1")
        ):
            raise ValueError("TAUVSYNC requires HTTPS except on localhost")
        if not parsed.hostname:
            raise ValueError("Invalid server URL")
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        # Never persist lease secrets; expired sessions must reacquire explicitly.
        self.edit_tokens: dict[str, str] = {}
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookies),
            _SameOriginRedirect(self.base),
        )
        # Identify the client explicitly: some HTTPS gateways reject
        # urllib's default Python-urllib/* User-Agent with HTTP 403.
        self.opener.addheaders = [("User-Agent", "TAUVSYNC-Client/1.0")]

    def _request(self, path: str, *, method: str = "GET", data=None, headers=None):
        request = urllib.request.Request(
            self.base + path, data=data, headers=headers or {}, method=method
        )
        try:
            return self.opener.open(request, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            error = f"Request failed (HTTP {exc.code})"
            try:
                payload = json.loads(exc.read(16384).decode("utf-8"))
                detail = payload.get("detail", error)
                if isinstance(detail, str):
                    error = detail
            except (ValueError, UnicodeError):
                pass
            raise APIError(error, exc.code) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise APIError(f"Connection failed: {exc}") from exc

    def _json(self, path: str, *, method: str = "GET", payload=None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        with self._request(
            path, method=method, data=data,
            headers={"Content-Type": "application/json"} if payload is not None else None,
        ) as response:
            return json.load(response)

    def login(self, email: str, password: str) -> dict:
        # Do not retain the password after making the request.
        result = self._json("/api/auth/login/password", method="POST", payload={
            "email": email, "password": password, "remember_me": False,
        })
        if result.get("must_change_password"):
            raise APIError("Change your password using the Prism website first")
        return result

    def logout(self):
        try:
            self._json("/api/auth/logout", method="POST", payload={})
        finally:
            self.cookies.clear()

    def projects(self) -> list[dict]:
        """Return live TAUV projects and reconcile registrations with Prism.

        No-cache headers prevent intermediary caches retaining deleted rows.
        Prism's registry is authoritative; an unavailable registry endpoint
        falls back to the existing TAUVSYNC cloud_state rather than hiding
        projects speculatively.
        """
        with self._request(
            "/api/tauvsync/projects",
            headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
        ) as response:
            projects = json.load(response)
        if not isinstance(projects, list):
            raise APIError("Invalid cloud project listing")
        try:
            with self._request(
                "/api/projects/",
                headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
            ) as response:
                registered = json.load(response)
            if not isinstance(registered, list):
                raise ValueError("Invalid Prism registry")
            active_ids = {str(p["id"]) for p in registered if isinstance(p, dict) and p.get("id")}
        except (APIError, ValueError, KeyError):
            return projects

        for item in projects:
            prism_id = item.get("prism_project_id")
            if prism_id and str(prism_id) not in active_ids:
                item["cloud_state"] = "missing_prism"
        return projects

    def thumbnail(self, prism_project_id: str, *, max_bytes: int = 8 * 1024 * 1024) -> bytes | None:
        """Fetch a registered Prism project's cached PCB thumbnail.

        A missing preview is normal for a newly created/empty project.
        Never pull large binary data into the UI or follow cross-origin redirects.
        """
        project = str(prism_project_id)
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", project):
            raise ValueError("Invalid Prism project identifier")
        try:
            with self._request(f"/api/projects/{project}/thumbnail") as response:
                content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
                if content_type not in ("image/png", "image/jpeg", "image/webp"):
                    raise APIError("Server returned an unsupported preview format")
                raw = response.read(max_bytes + 1)
                if len(raw) > max_bytes:
                    raise APIError("Project preview exceeds 8 MiB")
                return raw
        except APIError as error:
            if error.status == 404:
                return None
            raise

    def edit_lock(self, project_id: str) -> dict | None:
        return self._json(f"/api/tauvsync/projects/{_id(project_id)}/edit-lock")["edit_lock"]

    def has_edit_lock(self, project_id: str) -> bool:
        return project_id in self.edit_tokens

    def acquire_edit_lock(self, project_id: str) -> dict:
        if self.has_edit_lock(project_id):
            return self.renew_edit_lock(project_id)
        lease = self._json(
            f"/api/tauvsync/projects/{_id(project_id)}/edit-lock",
            method="POST", payload={},
        )
        token = lease.get("token")
        if not isinstance(token, str) or len(token) < 32:
            raise APIError("Server did not return a valid editing lock token")
        self.edit_tokens[project_id] = token
        return {"owner": lease["owner"], "expires_at": lease["expires_at"]}

    def renew_edit_lock(self, project_id: str) -> dict:
        token = self.edit_tokens.get(project_id)
        if not token:
            raise APIError("Open this project to acquire its exclusive editing lock")
        try:
            return self._json(
                f"/api/tauvsync/projects/{_id(project_id)}/edit-lock/renew",
                method="POST", payload={"token": token},
            )
        except APIError as error:
            if error.status in (404, 409, 423):
                self.edit_tokens.pop(project_id, None)
            raise

    def release_edit_lock(self, project_id: str) -> dict:
        token = self.edit_tokens.pop(project_id, None)
        if not token:
            return {"released": False}
        return self._json(
            f"/api/tauvsync/projects/{_id(project_id)}/edit-lock",
            method="DELETE", payload={"token": token},
        )

    def release_all_edit_locks(self):
        # Best effort only. Server TTL recovers from connection loss and crashes.
        for pid in tuple(self.edit_tokens):
            try:
                self.release_edit_lock(pid)
            except APIError:
                pass

    def revisions(self, project_id: str) -> list[dict]:
        return self._json(f"/api/tauvsync/projects/{_id(project_id)}/revisions")

    def download(self, project_id: str, revision: int, target: Path, *, max_bytes=512 * 1024 ** 2):
        path = f"/api/tauvsync/projects/{_id(project_id)}/revisions/{int(revision)}/download"
        target = Path(target)
        try:
            with self._request(path) as response, target.open("xb") as dest:
                size = 0
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > max_bytes:
                        raise APIError("Download exceeds 512 MiB")
                    dest.write(chunk)
        except Exception:
            target.unlink(missing_ok=True)
            raise

    def _check_gateway_upload(self, total_bytes: int) -> None:
        """Avoid guaranteed HTTP 413 from the team's Free-plan Worker URL.

        The server supports larger archives, but the HTTPS gateway rejects
        requests greater than 100 million bytes on the present Free tier.
        """
        parsed = urllib.parse.urlsplit(self.base)
        if parsed.hostname == "tauvsync-gateway.umutcanbahadir.workers.dev" and total_bytes > 100_000_000:
            raise APIError(
                "Project ZIP exceeds the current TAUV Cloudflare gateway's 100 MB "
                "upload limit. No upload was attempted; local files are safe.",
                status=413,
            )

    def create(self, name: str, archive: Path) -> dict:
        """Create a cloud project from an existing complete KiCad project ZIP."""
        name = name.strip()
        if not name or len(name) > 200:
            raise ValueError("Enter a project name (at most 200 characters)")
        archive = Path(archive)
        if archive.stat().st_size > 512 * 1024 ** 2:
            raise APIError("Upload exceeds 512 MiB")
        boundary = "tauvsync-" + uuid.uuid4().hex
        header = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="name"\r\n\r\n'
        ).encode() + name.encode("utf-8") + (
            f"\r\n--{boundary}\r\n"
            'Content-Disposition: form-data; name="archive"; filename="project.zip"\r\n'
            "Content-Type: application/zip\r\n\r\n"
        ).encode()
        footer = f"\r\n--{boundary}--\r\n".encode()
        size = archive.stat().st_size

        def chunks():
            yield header
            with archive.open("rb") as inp:
                while piece := inp.read(1024 * 1024):
                    yield piece
            yield footer

        self._check_gateway_upload(len(header) + size + len(footer))
        with self._request("/api/tauvsync/projects", method="POST",
                           data=chunks(), headers={
                               "Content-Type": f"multipart/form-data; boundary={boundary}",
                               "Content-Length": str(len(header) + size + len(footer)),
                           }) as response:
            return json.load(response)

    def publish(self, project_id: str, base_revision: int, archive: Path) -> dict:
        """Stream multipart body rather than loading large ZIPs into RAM."""
        archive = Path(archive)
        token = self.edit_tokens.get(project_id)
        if not token:
            raise APIError("Project is not locked for editing on this computer", status=423)
        boundary = "tauvsync-" + uuid.uuid4().hex
        header = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="base_revision"\r\n\r\n'
            f"{int(base_revision)}\r\n"
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="edit_token"\r\n\r\n'
            + token + "\r\n"
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="archive"; filename="project.zip"\r\n'
            "Content-Type: application/zip\r\n\r\n"
        ).encode()
        footer = f"\r\n--{boundary}--\r\n".encode()
        size = archive.stat().st_size
        if size > 512 * 1024 ** 2:
            raise APIError("Upload exceeds 512 MiB")
        def chunks():
            yield header
            with archive.open("rb") as inp:
                while piece := inp.read(1024 * 1024):
                    yield piece
            yield footer
        self._check_gateway_upload(len(header) + size + len(footer))
        path = f"/api/tauvsync/projects/{_id(project_id)}/revisions"
        with self._request(path, method="POST", data=chunks(), headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(header) + size + len(footer)),
        }) as response:
            return json.load(response)

    def restore(self, project_id: str, revision: int) -> dict:
        """Restore an historical snapshot as a new current revision.

        The server preserves all previous revisions; this operation requires a
        deliberate user confirmation in the UI and Designer/Admin permission.
        """
        return self._json(
            f"/api/tauvsync/projects/{_id(project_id)}/revisions/{int(revision)}/restore",
            method="POST", payload={"edit_token": self.edit_tokens.get(project_id) or ""},
        )


class _SameOriginRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, origin: str):
        self.origin = urllib.parse.urlsplit(origin)

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlsplit(newurl)
        if (parsed.scheme, parsed.netloc) != (self.origin.scheme, self.origin.netloc):
            raise APIError("Cross-origin redirect refused")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _id(project_id: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{32}", project_id):
        raise ValueError("Invalid project ID")
    return project_id
