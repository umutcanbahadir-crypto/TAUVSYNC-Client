"""Regression tests: polling KiCad editor state must never flash a Windows console."""
from types import SimpleNamespace
from unittest import mock
import unittest

from client.tauvsync import sync


class WindowsEditorPollingTests(unittest.TestCase):
    def test_tasklist_launch_does_not_create_console(self):
        completed = SimpleNamespace(stdout='"pcbnew.exe","123","Console","1"\n',
                                    returncode=0)
        with mock.patch.object(sync.sys, "platform", "win32"), \
             mock.patch.object(sync.subprocess, "run", return_value=completed) as launch:
            self.assertTrue(sync.editor_running())

        self.assertEqual(launch.call_args.args[0],
                         ["tasklist", "/FO", "CSV", "/NH"])
        flags = launch.call_args.kwargs.get("creationflags", 0)
        self.assertTrue(flags & 0x08000000, "CREATE_NO_WINDOW flag required")

    def test_no_editor_running(self):
        completed = SimpleNamespace(stdout='"explorer.exe","500"\n',
                                    returncode=0)
        with mock.patch.object(sync.sys, "platform", "win32"), \
             mock.patch.object(sync.subprocess, "run", return_value=completed):
            self.assertFalse(sync.editor_running())

    def test_tasklist_failure_prevents_unsafe_replacement(self):
        with mock.patch.object(sync.sys, "platform", "win32"), \
             mock.patch.object(sync.subprocess, "run", side_effect=OSError("unavailable")):
            self.assertTrue(sync.editor_running())


if __name__ == "__main__":
    unittest.main()
