"""Ubuntu 22.04 client compatibility contract without a running desktop."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from client.tauvsync import credentials
from client.tauvsync.kicad_launcher import find_linux_kicad10, launch_kicad_project


class LinuxCredentialTests(unittest.TestCase):
    def test_secret_service_store_and_lookup_not_written_as_plaintext(self):
        with mock.patch.object(credentials.sys, "platform", "linux"), \
             mock.patch.object(credentials, "_secret_tool") as tool:
            tool.return_value = subprocess.CompletedProcess([], 0, stdout="pw with spaces\n")
            credentials.store_login("https://sync.example.test/", "me@example.test", "pw with spaces")
            self.assertEqual(tool.call_args.args, (
                "store", "--label=TAUVSYNC login", "service", "TAUVSYNC",
                "url", "https://sync.example.test", "email", "me@example.test",
            ))
            self.assertEqual(tool.call_args.kwargs["password"], "pw with spaces")
            self.assertEqual(credentials.load_login("https://sync.example.test", "me@example.test"), "pw with spaces")
            credentials.forget_login("https://sync.example.test", "me@example.test")
            self.assertEqual(tool.call_args.args[0], "clear")

    def test_secret_service_unavailable_must_not_return_fake_login(self):
        with mock.patch.object(credentials.sys, "platform", "linux"), \
             mock.patch.object(credentials, "_secret_tool",
                 side_effect=credentials.CredentialStoreUnavailable("No keyring")):
            self.assertIsNone(credentials.load_login("https://sync.example.test", "me@example.test"))
            with self.assertRaises(credentials.CredentialStoreUnavailable):
                credentials.store_login("https://sync.example.test", "me@example.test", "password")

    def test_tool_receives_password_only_over_stdin(self):
        with mock.patch.object(credentials.sys, "platform", "linux"), \
             mock.patch.object(credentials.subprocess, "run",
                 return_value=subprocess.CompletedProcess([], 0)) as execute:
            sample = "not-in-argv"
            credentials._secret_tool("store", "service", "TAUVSYNC", password=sample)
            cmd = execute.call_args.args[0]
            self.assertNotIn("not-in-argv", cmd)
            self.assertEqual(execute.call_args.kwargs["input"], "not-in-argv")
            self.assertTrue(execute.call_args.kwargs["capture_output"])


class LinuxKiCadTests(unittest.TestCase):
    def test_requires_kicad10_even_if_an_older_version_is_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "kicad"
            exe.write_bytes(b"test")
            with mock.patch("client.tauvsync.kicad_launcher.subprocess.run") as run:
                run.return_value = subprocess.CompletedProcess([], 0, stdout="10.0.7\n", stderr="")
                self.assertEqual(find_linux_kicad10(environ={"TAUV_KICAD10_EXE": str(exe)}), exe.resolve())
                run.return_value = subprocess.CompletedProcess([], 0, stdout="6.0.11", stderr="")
                with self.assertRaisesRegex(RuntimeError, "requires KiCad 10"):
                    find_linux_kicad10(environ={"TAUV_KICAD10_EXE": str(exe)})

    def test_linux_opens_executable_not_xdg_default_association(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "foo.kicad_pro"
            project.write_text("{}")
            executable = Path(tmp) / "kicad"
            with mock.patch("client.tauvsync.kicad_launcher.find_linux_kicad10",
                            return_value=executable), \
                 mock.patch("client.tauvsync.kicad_launcher.subprocess.Popen") as popen:
                launch_kicad_project(project, platform="linux")
                popen.assert_called_once_with(
                    [str(executable), str(project.resolve())], close_fds=True
                )


if __name__ == "__main__":
    unittest.main()
