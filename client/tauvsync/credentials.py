"""Opt-in Windows user-bound credential storage for the TAUVSYNC desktop client.

The password is never written as plaintext. Windows DPAPI protects it for the
current Windows user. No password is persisted on other operating systems.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
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


def store_login(url: str, email: str, password: str) -> None:
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
    if not CREDENTIALS.is_file():
        return None
    try:
        record = json.loads(_protect(CREDENTIALS.read_bytes(), decrypt=True))
        if record.get("url") == url.rstrip("/") and record.get("email") == email:
            return record.get("password")
    except (OSError, ValueError, TypeError):
        return None
    return None


def forget_login() -> None:
    CREDENTIALS.unlink(missing_ok=True)
