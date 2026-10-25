"""Updates: finding a newer release, and swapping the executable for it (no network, no real restart)."""

import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sparescreen import panel, update
from sparescreen.config import ConfigStore

RELEASE = {
    "tag_name": "v0.12.0",
    "html_url": "https://github.com/gustacassel/SpareScreen/releases/tag/v0.12.0",
    "assets": [
        {"name": "sparescreen-windows-x64.exe", "browser_download_url": "https://example.test/win.exe"},
        {"name": "sparescreen-linux-x64", "browser_download_url": "https://example.test/linux"},
        {"name": "SHA256SUMS", "browser_download_url": "https://example.test/sums"},
    ],
}
NEW = b"the new version"


class Response(io.BytesIO):
    """Stands in for urlopen()'s response."""

    def __init__(self, data):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}


class VersionTest(unittest.TestCase):
    def test_parse_and_compare(self):
        self.assertEqual(update.parse_version("v0.11.0"), (0, 11, 0))
        self.assertEqual(update.parse_version("1.2"), (1, 2))
        self.assertEqual(update.parse_version("v1.0-beta"), ())
        self.assertEqual(update.parse_version(None), ())
        self.assertTrue(update.is_newer("0.12.0", "0.11.0"))
        self.assertTrue(update.is_newer("0.10.0", "0.9.9"))  # numbers, not text
        self.assertFalse(update.is_newer("0.11.0", "0.11.0"))
        self.assertFalse(update.is_newer("0.10.0", "0.11.0"))
        self.assertFalse(update.is_newer("nonsense", "0.11.0"))

    def test_parse_sums(self):
        digest = "a" * 64
        text = f"{digest}  sparescreen-linux-x64\n{'B' * 64} *sparescreen-windows-x64.exe\nnot a line\n"
        self.assertEqual(update.parse_sums(text), {"sparescreen-linux-x64": digest,
                                                   "sparescreen-windows-x64.exe": "b" * 64})


class CheckTest(unittest.TestCase):
    def test_finds_a_newer_release(self):
        updater = update.Updater(current="0.11.0", frozen=True, platform="win32")
        with mock.patch.object(update, "_get", return_value=json.dumps(RELEASE).encode()):
            updater.check()
        self.assertEqual(updater.available(), "0.12.0")
        self.assertTrue(updater.can_install())
        self.assertEqual(updater.read(), {"version": "0.11.0", "latest": "0.12.0"})
        self.assertIsNone(updater.error)

    def test_up_to_date(self):
        updater = update.Updater(current="0.12.0", frozen=True, platform="win32")
        with mock.patch.object(update, "_get", return_value=json.dumps(RELEASE).encode()):
            updater.check()
        self.assertIsNone(updater.available())
        self.assertFalse(updater.can_install())

    def test_failures_are_kept_not_raised(self):
        updater = update.Updater(current="0.11.0")
        for problem in (OSError("offline"), b"not json", json.dumps({"tag_name": "nightly"}).encode(),
                        json.dumps(["unexpected"]).encode()):
            with mock.patch.object(update, "_get", side_effect=problem if isinstance(problem, Exception) else None,
                                   return_value=problem):
                updater.check()
            self.assertIn("Couldn't check for updates", updater.error)
            self.assertIsNone(updater.available())
            self.assertEqual(updater.status, "idle")

    def test_only_the_packaged_executable_installs(self):
        updater = update.Updater(current="0.11.0", frozen=False, platform="win32")
        updater.latest = {"version": "0.12.0", "url": "u", "assets": {"sparescreen-windows-x64.exe": "x",
                                                                      "SHA256SUMS": "s"}}
        self.assertFalse(updater.can_install())
        self.assertTrue(updater.how())

    def test_no_checksums_or_no_file_for_this_system(self):
        updater = update.Updater(current="0.11.0", frozen=True, platform="darwin")
        updater.latest = {"version": "0.12.0", "url": "u", "assets": {"sparescreen-macos-arm64": "x"}}
        self.assertFalse(updater.can_install())
        self.assertIn("checksums", updater.how())
        updater.latest["assets"] = {"SHA256SUMS": "s"}
        self.assertIn("no file for this system", updater.how())

    def test_setting_turns_the_check_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = ConfigStore(Path(tmp) / "config.json")
            self.assertTrue(update.Updater(config).enabled())  # on by default
            config.update({"update_check": False})
            self.assertFalse(update.Updater(config).enabled())


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.exe = Path(self.tmp.name) / "sparescreen-windows-x64.exe"
        self.exe.write_bytes(b"the old version")
        self.updater = update.Updater(current="0.11.0", frozen=True, executable=str(self.exe), platform="win32")
        self.updater.latest = {"version": "0.12.0", "url": "u",
                               "assets": {a["name"]: a["browser_download_url"] for a in RELEASE["assets"]}}
        self.updater.quit = mock.Mock()

    def tearDown(self):
        self.tmp.cleanup()

    def run_install(self, data=NEW, listed="sparescreen-windows-x64.exe", version_output="SpareScreen 0.12.0\n"):
        sums = f"{hashlib.sha256(NEW).hexdigest()}  {listed}\n"
        ran = subprocess.CompletedProcess([], 0, stdout=version_output, stderr="")
        with mock.patch.object(update, "_get", return_value=sums.encode()), \
                mock.patch.object(update.urllib.request, "urlopen", return_value=Response(data)), \
                mock.patch.object(update.subprocess, "run", return_value=ran) as run:
            self.updater.status = "downloading"
            self.updater._install()  # what install() runs on its thread
        return run

    def test_swaps_and_restarts(self):
        run = self.run_install()
        self.assertEqual(self.exe.read_bytes(), NEW)
        self.assertEqual(self.updater.old_file.read_bytes(), b"the old version")
        self.assertFalse(self.updater.new_file.exists())
        self.assertEqual(run.call_args[0][0], [str(self.updater.new_file), "--version"])
        self.assertEqual(self.updater.status, "restarting")
        self.assertTrue(self.updater.relaunch_wanted)
        self.updater.quit.assert_called_once()

    def check_untouched(self, message):
        self.assertEqual(self.exe.read_bytes(), b"the old version")
        self.assertFalse(self.updater.new_file.exists())
        self.assertFalse(self.updater.old_file.exists())
        self.assertEqual(self.updater.status, "failed")
        self.assertIn(message, self.updater.error)
        self.assertFalse(self.updater.relaunch_wanted)
        self.updater.quit.assert_not_called()

    def test_wrong_checksum_is_discarded(self):
        self.run_install(data=b"something else")
        self.check_untouched("checksum")

    def test_checksums_without_this_file(self):
        self.run_install(listed="sparescreen-linux-x64")
        self.check_untouched("don't list")

    def test_a_file_that_does_not_start_is_not_installed(self):
        self.run_install(version_output="")
        self.check_untouched("didn't start")

    def test_clean_up_removes_the_old_file(self):
        self.updater.old_file.write_bytes(b"left over")
        with mock.patch.object(update.threading, "Thread") as thread:
            self.updater.clean_up()
        thread.call_args[1]["target"]()  # run the removal here instead of on a thread
        self.assertFalse(self.updater.old_file.exists())


class RelaunchTest(unittest.TestCase):
    def test_windows_starts_a_windowless_copy(self):
        with mock.patch.object(sys, "platform", "win32"), \
                mock.patch.object(sys, "argv", ["sparescreen.exe", "--no-usb"]), \
                mock.patch.object(sys, "executable", r"C:\Apps\sparescreen.exe"), \
                mock.patch.object(update.subprocess, "Popen") as popen:
            update.relaunch({"EXTRA": "1"})
        args, kwargs = popen.call_args
        self.assertEqual(args[0], [r"C:\Apps\sparescreen.exe", "--no-usb", "--background"])
        self.assertEqual(kwargs["env"]["EXTRA"], "1")
        self.assertEqual(kwargs["env"]["PYINSTALLER_RESET_ENVIRONMENT"], "1")

    def test_others_replace_the_process(self):
        with mock.patch.object(sys, "platform", "linux"), \
                mock.patch.object(sys, "argv", ["sparescreen", "--no-usb"]), \
                mock.patch.object(sys, "executable", "/opt/sparescreen"), \
                mock.patch.object(update.os, "execve", create=True) as execve:
            update.relaunch()
        self.assertEqual(execve.call_args[0][:2], ("/opt/sparescreen", ["/opt/sparescreen", "--no-usb"]))


class PanelTest(unittest.TestCase):
    def setUp(self):
        self.updater = update.Updater(current="0.11.0", frozen=True, platform="win32")

    def test_check_row(self):
        p = panel.Panel(updater=self.updater)
        self.assertEqual(p._update_check()["action"]["id"], "update_check_now")
        self.updater.checked_at = 1
        self.assertIn("Up to date", p._update_check()["detail"])
        self.updater.latest = {"version": "0.12.0", "url": "u", "assets": {}}
        self.assertIn("0.12.0 is available", p._update_check()["detail"])
        self.assertIsNone(panel.Panel()._update_check())

    def test_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = ConfigStore(Path(tmp) / "config.json")
            p = panel.Panel(updater=self.updater, config=config)
            with mock.patch.object(self.updater, "install") as install:
                self.assertTrue(p.act("update_install")["ok"])
            install.assert_called_once()
            self.assertTrue(p.act("update_auto", {"on": False})["ok"])
            self.assertFalse(config.read()["update_check"])


if __name__ == "__main__":
    unittest.main()
