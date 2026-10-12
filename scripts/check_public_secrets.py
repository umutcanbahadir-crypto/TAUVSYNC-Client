"""Reject accidentally committed credentials in the public TAUV client repository.

Run with: python scripts/check_public_secrets.py
Scans *tracked* files only, including tests and documentation, without
printing matched secret values. Keep real credentials outside this repository.
This guard complements (not replaces) GitHub secret scanning.
"""
from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys


PATTERNS = {
    "private key": re.compile(r"-----BEGIN\s+(?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "GitHub access token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    "AWS access key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "personal email address": re.compile(
        r"[\w.+-]+@(?:gmail\.com|googlemail\.com|hotmail\.com|outlook\.com|"
        r"icloud\.com|yahoo\.com|yandex\.com|proton\.me|protonmail\.com)\b",
        re.IGNORECASE,
    ),
    "literal assigned password or token": re.compile(
        r"\b(?:password|passwd|secret|api_key|client_secret|access_token)"
        r"\s*=\s*['\"][^'\"\n]{9,}['\"]",
        re.IGNORECASE,
    ),
}
BLOCKED_FILENAMES = {
    ".env", "id_rsa", "id_ed25519", "credentials.json", "secrets.json",
    "login.dpapi", ".tauvsync-client.json",
}
BLOCKED_SUFFIXES = (".pem", ".p12", ".pfx", ".key", ".dpapi")
MAX_TEXT_SIZE = 2 * 1024 * 1024


def inspect_file(path: str, payload: bytes) -> list[str]:
    name = Path(path).name.lower()
    if name in BLOCKED_FILENAMES or name.endswith(BLOCKED_SUFFIXES):
        return ["private configuration file"]
    if len(payload) > MAX_TEXT_SIZE or b"\0" in payload:
        return []  # Binary assets are not treated as source; release artifacts are CI-built.
    text = payload.decode("utf-8", errors="replace")
    findings = [label for label, pattern in PATTERNS.items() if pattern.search(text)]
    # Intentional dummy credentials in protocol tests can use the reserved
    # example.com / example.test domains. Never allow actual public domains.
    url_pattern = re.compile(r"https?://([^/@:\s]+):([^/@\s]+)@([A-Za-z0-9.-]+)")
    for match in url_pattern.finditer(text):
        if match.group(3).lower() not in ("example.com", "example.test", "example.invalid"):
            findings.append("embedded URL credentials")
            break
    return findings


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    failures = []
    for relative in result.stdout.decode("utf-8").split("\0"):
        if not relative:
            continue
        path = root / relative
        if not path.is_file():
            continue
        labels = inspect_file(relative, path.read_bytes())
        if labels:
            failures.append((relative, labels))
    for relative, labels in failures:
        print(f"ERROR: {relative}: {', '.join(labels)}", file=sys.stderr)
    if failures:
        print("Remove secrets from the public repository before releasing.", file=sys.stderr)
        return 1
    print("Public client secret guard passed (tracked files).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
