"""Managed OpenSSH port forwarding for the Windows KiCad desktop client.

Never bypass SSH known-host verification. The tunnel only binds loopback;
the remote TAUVSYNC HTTP port must also be bound to server loopback.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time


class TunnelError(RuntimeError):
    pass


@dataclass(frozen=True)
class TunnelConfig:
    host: str
    user: str = "user"
    key: str = "~/.ssh/id_ed25519"
    ssh_port: int = 22
    remote_port: int = 18080

    def validated(self) -> "TunnelConfig":
        host = self.host.strip().lower()
        user = self.user.strip()
        port = int(self.ssh_port)
        remote = int(self.remote_port)
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,252}", host) or ".." in host:
            raise TunnelError("Enter a valid SSH server hostname or IPv4 address")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9-]{0,63}", user):
            raise TunnelError("Invalid SSH username")
        if not 1 <= port <= 65535 or not 1 <= remote <= 65535:
            raise TunnelError("Invalid SSH port")
        path = Path(self.key).expanduser()
        if not path.is_file():
            raise TunnelError(f"SSH private key was not found: {path}")
        return TunnelConfig(host, user, str(path.resolve()), port, remote)

    def credential_id(self) -> str:
        """Stable credential identity, independent of ephemeral local port."""
        return f"ssh://{self.user.strip()}@{self.host.strip().lower()}:{int(self.ssh_port)}/{int(self.remote_port)}"


def _unused_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def _listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.25):
            return True
    except OSError:
        return False


class ManagedSshTunnel:
    def __init__(self, config: TunnelConfig, *, wait_seconds: float = 12):
        self.config = config.validated()
        self.wait_seconds = wait_seconds
        self.port = _unused_loopback_port()
        self.process = None
        self._stderr = None
        self._lock = threading.RLock()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def ensure_running(self) -> str:
        """Launch/restart in background; call from a worker thread, not Tk."""
        with self._lock:
            if self.process is not None and self.process.poll() is None:
                return self.url
            if _listening(self.port):
                # Never send user credentials to a different process owning our port.
                raise TunnelError(f"Local port {self.port} is in use; refusing to connect")
            ssh = shutil.which("ssh")
            if not ssh:
                raise TunnelError("Windows OpenSSH client (ssh.exe) is missing")
            cmd = [
                ssh, "-N", "-T", "-o", "BatchMode=yes",
                "-o", "StrictHostKeyChecking=yes",
                "-o", "ExitOnForwardFailure=yes",
                "-o", "IdentitiesOnly=yes",
                "-o", "PasswordAuthentication=no",
                "-o", "KbdInteractiveAuthentication=no",
                "-o", "ConnectTimeout=10",
                "-o", "ServerAliveInterval=20",
                "-o", "ServerAliveCountMax=3",
                "-p", str(self.config.ssh_port),
                "-i", self.config.key,
                "-L", f"127.0.0.1:{self.port}:127.0.0.1:{self.config.remote_port}",
                f"{self.config.user}@{self.config.host}",
            ]
            if self._stderr is not None:
                self._stderr.close()
            self._stderr = tempfile.TemporaryFile(mode="w+b")
            try:
                self.process = subprocess.Popen(
                    cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=self._stderr,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    if sys.platform == "win32" else 0,
                )
            except OSError as exc:
                raise TunnelError(f"Could not start ssh.exe: {exc}") from exc
            deadline = time.monotonic() + self.wait_seconds
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    self._stderr.seek(0)
                    reason = self._stderr.read().decode(errors="replace")[-1200:].strip()
                    raise TunnelError(
                        "SSH tunnel failed: " + (reason or "Check server, key, and known_hosts")
                    )
                if _listening(self.port):
                    return self.url
                time.sleep(0.15)
            self.process.terminate()
            raise TunnelError("SSH tunnel did not start within the connection timeout")

    def close(self) -> None:
        with self._lock:
            if self.process is not None and self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=3)
            self.process = None
            if self._stderr is not None:
                self._stderr.close()
                self._stderr = None
