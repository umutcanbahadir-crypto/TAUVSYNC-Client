"""Non-blocking GitHub Releases update discovery for the public Windows client.

Only official TAUVSYNC-Client releases carrying TAUVSYNC.exe are offered.
The caller owns the UI thread; this module performs no installation or writes.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
from urllib.parse import quote
from urllib.request import Request, urlopen

APP_VERSION = "2.2.1"
RELEASES_API = "https://api.github.com/repos/umutcanbahadir-crypto/TAUVSYNC-Client/releases?per_page=20"
RELEASES_BASE = "https://github.com/umutcanbahadir-crypto/TAUVSYNC-Client/releases/tag/"
_VERSION_RE = re.compile(
    r"^v?(\d+)\.(\d+)\.(\d+)(?:[-.]?(a|alpha|b|beta|rc)[.-]?(\d*))?$",
    re.IGNORECASE,
)
_PRERELEASE_ORDER = {"a": 0, "alpha": 0, "b": 1, "beta": 1, "rc": 2}


@dataclass(frozen=True)
class AvailableUpdate:
    version: str
    release_url: str


def version_key(version: str) -> tuple[int, int, int, int, int] | None:
    """Compare numeric releases, including alpha/beta/RC suffixes."""
    if not isinstance(version, str):
        return None
    match = _VERSION_RE.fullmatch(version)
    if match is None:
        return None
    major, minor, patch, stage, sequence = match.groups()
    rank = _PRERELEASE_ORDER[stage.lower()] if stage else 3
    return (int(major), int(minor), int(patch), rank, int(sequence or 0))


def select_update(releases: object, installed_version: str = APP_VERSION) -> AvailableUpdate | None:
    """Select the newest newer published release with a Windows EXE asset."""
    installed = version_key(installed_version)
    if installed is None or not isinstance(releases, list):
        return None

    best: tuple[int, int, int, int, int] | None = None
    selected: AvailableUpdate | None = None
    for release in releases:
        if not isinstance(release, dict) or release.get("draft"):
            continue
        tag = release.get("tag_name")
        candidate = version_key(tag)
        if candidate is None or candidate <= installed:
            continue
        assets = release.get("assets")
        if not isinstance(assets, list) or not any(
            isinstance(asset, dict) and asset.get("name") == "TAUVSYNC.exe"
            for asset in assets
        ):
            continue
        if best is None or candidate > best:
            best = candidate
            selected = AvailableUpdate(
                version=tag.removeprefix("v"),
                release_url=RELEASES_BASE + quote(tag, safe=""),
            )
    return selected


def check_for_update(timeout: float = 4.0) -> AvailableUpdate | None:
    """Fetch release metadata without credentials. Network errors are non-fatal."""
    request = Request(
        RELEASES_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "TAUVSYNC-Client-update-check",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read(1024 * 1024 + 1)
        if len(payload) > 1024 * 1024:
            return None
        return select_update(json.loads(payload))
    except (OSError, ValueError, TypeError, UnicodeError):
        # Offline, rate-limited or invalid response: open normally, no popup.
        return None
