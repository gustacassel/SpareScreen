import plistlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from sparescreen import autostart
from sparescreen.cli import without


class WithoutTest(unittest.TestCase):
    def test_drops_flags_and_their_values(self):
        argv = ["--port", "9000", "--autostart", "on", "--stay-awake", "--background", "--dev"]
        self.assertEqual(without(argv, "--autostart", "--background", "--dev"), ["--port", "9000", "--stay-awake"])
        self.assertEqual(without(["--autostart=on", "--no-usb"], "--autostart"), ["--no-usb"])


class LaunchCommandTest(unittest.TestCase):
    def test_source_install_runs_the_module_in_background(self):
        with mock.patch.object(sys, "frozen", False, create=True):
            command = autostart.launch_command(["--port", "9000"])
        self.assertEqual(command[-4:], ["sparescreen", "--port", "9000", "--background"])
        self.assertEqual(command[-5], "-m")

    def test_packaged_executable_runs_itself(self):
        with mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.object(sys, "executable", "/apps/sparescreen"):
            self.assertEqual(autostart.launch_command([]), ["/apps/sparescreen", "--background"])


class PerOsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_linux_desktop_entry(self):
        desktop = self.dir / "autostart" / "sparescreen.desktop"
        with mock.patch.object(autostart.sys, "platform", "linux"), \
                mock.patch.object(autostart, "DESKTOP_FILE", desktop):
            self.assertIsNone(autostart.status())
            autostart.enable(["--stay-awake"])
            self.assertIn("Exec=", desktop.read_text(encoding="utf-8"))
            self.assertIn("--stay-awake", autostart.status())
            self.assertIn("--background", autostart.status())
            autostart.disable()
            self.assertIsNone(autostart.status())
            autostart.disable()  # already off: no error

    def test_macos_launch_agent(self):
        agent = self.dir / "LaunchAgents" / "io.github.gustacassel.sparescreen.plist"
        with mock.patch.object(autostart.sys, "platform", "darwin"), \
                mock.patch.object(autostart, "LAUNCH_AGENT", agent):
            autostart.enable([])
            with open(agent, "rb") as f:
                plist = plistlib.load(f)
            self.assertTrue(plist["RunAtLoad"])
            self.assertEqual(plist["ProgramArguments"][-1], "--background")
            self.assertIn("--background", autostart.status())
            autostart.disable()
            self.assertFalse(agent.exists())

    def test_windows_registry(self):
        store = {}

        class Key:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def delete(key, name):
            if name not in store:
                raise FileNotFoundError
            del store[name]

        def query(key, name):
            if name not in store:
                raise FileNotFoundError
            return store[name], 1

        fake = types.SimpleNamespace(
            HKEY_CURRENT_USER=1, KEY_SET_VALUE=2, REG_SZ=1,
            OpenKey=lambda *a: Key(),
            SetValueEx=lambda key, name, reserved, kind, value: store.__setitem__(name, value),
            DeleteValue=delete, QueryValueEx=query,
        )
        with mock.patch.object(autostart.sys, "platform", "win32"), \
                mock.patch.dict(sys.modules, {"winreg": fake}):
            self.assertIsNone(autostart.status())
            autostart.enable(["--no-usb"])
            self.assertIn("--no-usb", store["SpareScreen"])
            self.assertIn("--background", autostart.status())
            autostart.disable()
            self.assertIsNone(autostart.status())
            autostart.disable()


if __name__ == "__main__":
    unittest.main()
