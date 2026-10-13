"""Opt-in native credential storage: Windows DPAPI or Linux Secret Service.

No credentials are stored in preferences, logs, GitHub, or project files.
On Linux, secret-tool communicates with the current user's unlocked keyring.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys

CREDENTIALS = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "TAUVSYNC" / "login.dpapi"


class CredentialStoreUnavailable(RuntimeError):
    pass


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _protect(payload: bytes, *, decrypt: bool = False) -> bytes:
    if sys.platform != "win32":
        raise CredentialStoreUnavailable("Remember password requires Windows DPAPI")
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    operation = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    operation.argtypes = (
        [ctypes.POINTER(_Blob), ctypes.POINTER(ctypes.c_wchar_p),
         ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p,
         wintypes.DWORD, ctypes.POINTER(_Blob)]
        if decrypt else
        [ctypes.POINTER(_Blob), ctypes.c_wchar_p,
         ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p,
         wintypes.DWORD, ctypes.POINTER(_Blob)]
    )
    operation.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    data = ctypes.create_string_buffer(payload)
    source = _Blob(len(payload), ctypes.cast(data, ctypes.POINTER(ctypes.c_ubyte)))
    dest = _Blob()
    if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(dest)):
        raise OSError(ctypes.get_last_error(), "Windows DPAPI operation failed")
    try:
        return ctypes.string_at(dest.pbData, dest.cbData)
    finally:
        kernel.LocalFree(ctypes.cast(dest.pbData, ctypes.c_void_p))


SERVICE = "TAUVSYNC"


def _secret_tool(*args: str, password: str | None = None,
                 timeout: float = 8.0) -> subprocess.CompletedProcess:
    """Use the desktop Secret Service without writing a password to disk or argv."""
    if sys.platform != "linux":
        raise CredentialStoreUnavailable("Linux Secret Service is unavailable")
    try:
        process = subprocess.run(
            ["secret-tool", *args], input=password, text=True,
            capture_output=True, timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CredentialStoreUnavailable(
            "Secure storage needs libsecret-tools and an unlocked desktop keyring"
        ) from error
    return process


def _linux_account(url: str, email: str) -> tuple[str, ...]:
    return ("service", SERVICE, "url", url.rstrip("/"), "email", email)


def store_login(url: str, email: str, password: str) -> None:
    if sys.platform == "linux":
        result = _secret_tool("store", "--label=TAUVSYNC login",
                              *_linux_account(url, email), password=password)
        if result.returncode:
            raise CredentialStoreUnavailable(
                "Cannot save login: unlock the GNOME keyring or disable Remember login"
            )
        return
    if sys.platform != "win32":
        raise CredentialStoreUnavailable("Secure remembered login is unavailable")
    record = json.dumps({"url": url.rstrip("/"), "email": email,
                         "password": password}).encode("utf-8")
    ciphertext = _protect(record)
    CREDENTIALS.parent.mkdir(parents=True, exist_ok=True)
    temp = CREDENTIALS.with_suffix(".tmp")
    try:
        temp.write_bytes(ciphertext)
        os.replace(temp, CREDENTIALS)
    finally:
        temp.unlink(missing_ok=True)


def load_login(url: str, email: str) -> str | None:
    if sys.platform == "linux":
        try:
            result = _secret_tool("lookup", *_linux_account(url, email), timeout=5)
            if result.returncode == 0 and result.stdout:
                return result.stdout.rstrip("\n")
        except CredentialStoreUnavailable:
            pass
        return None
    if sys.platform != "win32" or not CREDENTIALS.is_file():
        return None
    try:
        record = json.loads(_protect(CREDENTIALS.read_bytes(), decrypt=True))
        if record.get("url") == url.rstrip("/") and record.get("email") == email:
            return record.get("password")
    except (OSError, ValueError, TypeError):
        return None
    return None


def forget_login(url: str | None = None, email: str | None = None) -> None:
    if sys.platform == "linux":
        # The non-secret preferences identify which keyring item may be cleared.
        if not url or not email:
            try:
                prefs = json.loads((Path.home() / ".tauvsync-client.json").read_text(encoding="utf-8"))
                url, email = prefs.get("url"), prefs.get("email")
            except (OSError, ValueError, TypeError):
                return
        if url and email:
            try:
                _secret_tool("clear", *_linux_account(url, email), timeout=5)
            except CredentialStoreUnavailable:
                pass
        return
    if sys.platform == "win32":
        CREDENTIALS.unlink(missing_ok=True)
