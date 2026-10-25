"""Tray menu and the double-click handling of the Windows .exe (no real tray or console needed)."""

import subprocess
import sys
import unittest
from unittest import mock

from sparescreen import cli, tray


class Pairing:
    code = "123456"


class TrayMenuTest(unittest.TestCase):
    def test_entries(self):
        items = tray.entries("http://localhost:8765", "http://192.168.0.5:8765", Pairing(), ["--no-usb"])
        labels = [label() if callable(label) else label for label, _, _ in items]
        self.assertEqual(labels[:3], ["Open dashboard", "Phone: http://192.168.0.5:8765", "Pairing code: 123456"])
        self.assertEqual(labels[-1], "Quit")
        self.assertTrue(items[0][2]["default"])
        self.assertIsNone(items[1][1])  # information only

    def test_no_phone_address_or_pairing(self):
        labels = [label for label, _, _ in tray.entries("http://localhost:8765", None, None, [])]
        self.assertEqual(labels, ["Open dashboard", "-", tray.start_label(), "Quit"])

    def test_start_at_login_toggles(self):
        toggle = next(action for label, action, _ in tray.entries("u", None, None, ["--no-usb"])
                      if label == tray.start_label())
        with mock.patch.object(tray.autostart, "status", return_value=None), \
                mock.patch.object(tray.autostart, "enable") as enable:
            toggle()
        enable.assert_called_once_with(["--no-usb"])
        with mock.patch.object(tray.autostart, "status", return_value="cmd"), \
                mock.patch.object(tray.autostart, "disable") as disable:
            toggle()
        disable.assert_called_once()

    def test_labels_per_os(self):
        self.assertEqual(tray.start_label("win32"), "Start with Windows")
        self.assertEqual(tray.start_label("linux"), "Start when I log in")


class DoubleClickTest(unittest.TestCase):
    def test_autostart_args_drop_one_off_options(self):
        with mock.patch.object(sys, "argv", ["sparescreen", "--no-usb", "--background", "--autostart", "on"]):
            self.assertEqual(cli.autostart_args(), ["--no-usb"])

    def test_detach_starts_a_windowless_background_copy(self):
        flags = {"CREATE_NO_WINDOW": 0x08000000, "CREATE_NEW_PROCESS_GROUP": 0x200}
        with mock.patch.object(sys, "argv", ["sparescreen.exe", "--no-usb"]), \
                mock.patch.object(sys, "executable", r"C:\Apps\sparescreen.exe"), \
                mock.patch.multiple(subprocess, create=True, **flags), \
                mock.patch.object(subprocess, "Popen") as popen:
            cli.detach(greet=True)
        args, kwargs = popen.call_args
        self.assertEqual(args[0], [r"C:\Apps\sparescreen.exe", "--no-usb", "--background"])
        self.assertEqual(kwargs["env"][cli.DETACHED], "greet")
        self.assertEqual(kwargs["env"]["PYINSTALLER_RESET_ENVIRONMENT"], "1")

    def test_double_clicked_exe_hands_over_and_exits(self):
        with mock.patch.object(sys, "argv", ["sparescreen.exe"]), \
                mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.object(sys, "platform", "win32"), \
                mock.patch.dict("os.environ", {}, clear=False), \
                mock.patch.object(cli, "console_is_ours", return_value=True), \
                mock.patch.object(cli, "detach") as detach, \
                mock.patch.object(cli, "serve") as serve:
            cli.os.environ.pop(cli.DETACHED, None)
            self.assertEqual(cli.main(), 0)
        detach.assert_called_once_with(greet=True)
        serve.assert_not_called()


if __name__ == "__main__":
    unittest.main()
