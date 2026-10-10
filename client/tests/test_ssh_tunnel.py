"""Managed SSH tunnel tests; does not contact the Oracle server."""
from pathlib import Path
from unittest import mock
import socket
import tempfile
import unittest

from client.tauvsync.ssh_tunnel import ManagedSshTunnel, TunnelConfig, TunnelError
from client.tauvsync.app import configured_credential_id


class SshTunnelTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.key = Path(folder.name) / "dummy_ssh_key"
        self.key.write_text("dummy private key (never loaded in these mocks)")

    def test_ssh_config_is_private_key_only_and_credential_identity_stable(self):
        cfg = TunnelConfig("EXAMPLE.org", "testuser", str(self.key), ssh_port=22).validated()
        self.assertEqual(cfg.host, "example.org")
        self.assertEqual(cfg.credential_id(), "ssh://testuser@example.org:22/18080")
        pref = {"ssh": {"enabled": True, "host": "EXAMPLE.org",
                        "user": "testuser", "port": "22"}, "url": "http://127.0.0.1:18080"}
        self.assertEqual(configured_credential_id(pref), cfg.credential_id())
        self.assertEqual(configured_credential_id(
            {"ssh": {"enabled": False}, "url": "http://127.0.0.1:18080/"}),
            "http://127.0.0.1:18080")

    def test_dangerous_host_or_invalid_key_rejected(self):
        for host in ("-oProxyCommand=id", "localhost;touch /tmp/bad", "", "host name"):
            with self.assertRaises(TunnelError):
                TunnelConfig(host, key=str(self.key)).validated()
        with self.assertRaises(TunnelError):
            TunnelConfig("example.org", key=str(self.key) + ".missing").validated()

    def test_managed_ssh_uses_strict_host_verification_and_loopback(self):
        cfg = TunnelConfig("example.org", key=str(self.key))
        tunnel = ManagedSshTunnel(cfg)
        self.addCleanup(tunnel.close)
        process = mock.Mock()
        process.poll.return_value = None
        with mock.patch("client.tauvsync.ssh_tunnel.shutil.which", return_value="ssh.exe"), \
             mock.patch("client.tauvsync.ssh_tunnel._listening", side_effect=[False, True]), \
             mock.patch("client.tauvsync.ssh_tunnel.subprocess.Popen", return_value=process) as popen:
            self.assertEqual(tunnel.ensure_running(), tunnel.url)
        args = popen.call_args.args[0]
        self.assertIn("StrictHostKeyChecking=yes", args)
        self.assertIn("BatchMode=yes", args)
        self.assertIn("ExitOnForwardFailure=yes", args)
        self.assertNotIn("StrictHostKeyChecking=no", args)
        self.assertIn(f"127.0.0.1:{tunnel.port}:127.0.0.1:18080", args)
        self.assertEqual(args[-1], "user@example.org")
        self.assertNotIn("shell", popen.call_args.kwargs)
        tunnel.close()
        process.terminate.assert_called_once()

    def test_second_start_reuses_live_process_and_does_not_spawn_duplicate(self):
        cfg = TunnelConfig("example.org", key=str(self.key))
        tunnel = ManagedSshTunnel(cfg)
        self.addCleanup(tunnel.close)
        process = mock.Mock()
        process.poll.return_value = None
        with mock.patch("client.tauvsync.ssh_tunnel.shutil.which", return_value="ssh.exe"), \
             mock.patch("client.tauvsync.ssh_tunnel._listening", side_effect=[False, True]), \
             mock.patch("client.tauvsync.ssh_tunnel.subprocess.Popen", return_value=process) as popen:
            tunnel.ensure_running()
            tunnel.ensure_running()
            self.assertEqual(popen.call_count, 1)

    def test_refuses_to_use_local_port_owned_by_other_process(self):
        cfg = TunnelConfig("example.org", key=str(self.key))
        tunnel = ManagedSshTunnel(cfg)
        self.addCleanup(tunnel.close)
        with mock.patch("client.tauvsync.ssh_tunnel._listening", return_value=True), \
             mock.patch("client.tauvsync.ssh_tunnel.subprocess.Popen") as popen:
            with self.assertRaisesRegex(TunnelError, "port.*in use"):
                tunnel.ensure_running()
            popen.assert_not_called()

    def test_dead_ssh_process_is_relaunched_automatically(self):
        cfg = TunnelConfig("example.org", key=str(self.key))
        tunnel = ManagedSshTunnel(cfg)
        self.addCleanup(tunnel.close)
        first = mock.Mock()
        first.poll.side_effect = [None, 1]
        second = mock.Mock()
        second.poll.return_value = None
        with mock.patch("client.tauvsync.ssh_tunnel.shutil.which", return_value="ssh.exe"), \
             mock.patch("client.tauvsync.ssh_tunnel._listening",
                        side_effect=[False, True, False, True]), \
             mock.patch("client.tauvsync.ssh_tunnel.subprocess.Popen",
                        side_effect=[first, second]) as popen:
            tunnel.ensure_running()
            tunnel.ensure_running()
            self.assertEqual(popen.call_count, 2)


if __name__ == "__main__":
    unittest.main()
