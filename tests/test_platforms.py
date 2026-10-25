"""Platform-specific helpers (focused window, macOS temperature), with every OS call mocked."""

import json
import subprocess
import unittest
from unittest import mock

from sparescreen import activity, sensors


def _done(stdout, code=0):
    return subprocess.CompletedProcess([], code, stdout=stdout, stderr="")


def _which(*available):
    return lambda name: "/usr/bin/" + name if name in available else None


def _commands(outputs):
    """subprocess.run fake answering by the command's first two words (e.g. 'xprop -root')."""
    def run(args, **kwargs):
        key = " ".join([args[0].rsplit("/", 1)[-1]] + list(args[1:2]))
        out = outputs.get(key)
        if isinstance(out, Exception):
            raise out
        return _done(out) if out is not None else _done("", 1)
    return run


class LinuxFocusTest(unittest.TestCase):
    def focus(self, env, available, outputs):
        with mock.patch.object(activity.sys, "platform", "linux"), \
                mock.patch.dict(activity.os.environ, env, clear=True), \
                mock.patch.object(activity.shutil, "which", _which(*available)), \
                mock.patch.object(activity.subprocess, "run", _commands(outputs)):
            return activity.foreground_pid()

    def test_x11_with_xprop(self):
        outputs = {
            "xprop -root": "_NET_ACTIVE_WINDOW(WINDOW): window id # 0x3a00007\n",
            "xprop -id": "_NET_WM_PID(CARDINAL) = 4242\n",
        }
        self.assertEqual(self.focus({"DISPLAY": ":0"}, ["xprop"], outputs), 4242)

    def test_x11_prefers_xdotool(self):
        outputs = {"xdotool getactivewindow": "1234\n"}
        self.assertEqual(self.focus({"DISPLAY": ":0"}, ["xdotool", "xprop"], outputs), 1234)

    def test_x11_falls_back_to_xprop_when_xdotool_fails(self):
        outputs = {
            "xprop -root": "_NET_ACTIVE_WINDOW(WINDOW): window id # 0x1e00004\n",
            "xprop -id": "_NET_WM_PID(CARDINAL) = 77\n",
        }
        self.assertEqual(self.focus({"DISPLAY": ":0"}, ["xdotool", "xprop"], outputs), 77)

    def test_x11_nothing_focused_or_no_pid(self):
        self.assertIsNone(self.focus({"DISPLAY": ":0"}, ["xprop"],
                                     {"xprop -root": "_NET_ACTIVE_WINDOW(WINDOW): window id # 0x0\n"}))
        self.assertIsNone(self.focus({"DISPLAY": ":0"}, ["xprop"], {
            "xprop -root": "_NET_ACTIVE_WINDOW(WINDOW): window id # 0x3a00007\n",
            "xprop -id": "_NET_WM_PID:  not found.\n",
        }))

    def test_missing_tools_or_display(self):
        self.assertIsNone(self.focus({"DISPLAY": ":0"}, [], {}))
        self.assertIsNone(self.focus({}, ["xprop", "xdotool"], {"xdotool getactivewindow": "1234\n"}))

    def test_timeouts_and_errors_return_none(self):
        outputs = {"xprop -root": subprocess.TimeoutExpired("xprop", 1)}
        self.assertIsNone(self.focus({"DISPLAY": ":0"}, ["xprop"], outputs))
        outputs = {"xdotool getactivewindow": OSError("boom")}
        self.assertIsNone(self.focus({"DISPLAY": ":0"}, ["xdotool"], outputs))

    def test_plain_wayland_does_not_trust_xwayland(self):
        env = {"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0"}
        outputs = {"xdotool getactivewindow": "1234\n"}
        self.assertIsNone(self.focus(env, ["xdotool", "xprop"], outputs))

    def test_hyprland(self):
        env = {"WAYLAND_DISPLAY": "wayland-1", "HYPRLAND_INSTANCE_SIGNATURE": "abc"}
        outputs = {"hyprctl activewindow": json.dumps({"class": "firefox", "pid": 3100})}
        self.assertEqual(self.focus(env, ["hyprctl"], outputs), 3100)
        self.assertIsNone(self.focus(env, ["hyprctl"], {"hyprctl activewindow": "Invalid"}))
        self.assertIsNone(self.focus(env, ["hyprctl"], {"hyprctl activewindow": json.dumps({"pid": -1})}))

    def test_sway_finds_the_focused_window_anywhere_in_the_tree(self):
        tree = {"focused": False, "nodes": [
            {"focused": False, "nodes": [{"focused": False, "pid": 10, "nodes": []}]},
            {"focused": False, "nodes": [], "floating_nodes": [{"focused": True, "pid": 20, "nodes": []}]},
        ]}
        env = {"WAYLAND_DISPLAY": "wayland-1", "SWAYSOCK": "/run/user/1000/sway.sock"}
        self.assertEqual(self.focus(env, ["swaymsg"], {"swaymsg -t": json.dumps(tree)}), 20)
        self.assertIsNone(self.focus(env, [], {}))


class MacFocusTest(unittest.TestCase):
    def focus(self, available, outputs):
        with mock.patch.object(activity.sys, "platform", "darwin"), \
                mock.patch.object(activity.shutil, "which", _which(*available)), \
                mock.patch.object(activity.subprocess, "run", _commands(outputs)):
            return activity.foreground_pid()

    def test_lsappinfo(self):
        outputs = {"lsappinfo front": "ASN:0x0-0x1d01d:\n", "lsappinfo info": '"pid"=651\n'}
        self.assertEqual(self.focus(["lsappinfo"], outputs), 651)

    def test_lsappinfo_missing_or_failing(self):
        self.assertIsNone(self.focus([], {}))
        self.assertIsNone(self.focus(["lsappinfo"], {"lsappinfo front": "\n"}))
        self.assertIsNone(self.focus(["lsappinfo"], {"lsappinfo front": "ASN:0x0-0x1d01d:\n"}))


class FriendlyNameTest(unittest.TestCase):
    def setUp(self):
        activity._descriptions.clear()

    def test_capitalizes_lowercase_binaries_off_windows(self):
        with mock.patch.object(activity.sys, "platform", "linux"):
            self.assertEqual(activity.friendly_name("firefox", "/usr/lib/firefox/firefox"), "Firefox")
            self.assertEqual(activity.friendly_name("Xorg", "/usr/lib/Xorg"), "Xorg")
            self.assertEqual(activity.friendly_name("kworker", None), "kworker")


class MacTempTest(unittest.TestCase):
    def test_parsers(self):
        self.assertEqual(sensors.parse_mac_temp("smctemp", "64.2\n"), 64.2)
        self.assertEqual(sensors.parse_mac_temp("osx-cpu-temp", "61.8 °C\n"), 61.8)
        line = json.dumps({"temp": {"cpu_temp_avg": 43.73614, "gpu_temp_avg": 36.9}, "cpu_power": 1.2})
        self.assertAlmostEqual(sensors.parse_mac_temp("macmon", line + "\n"), 43.73614)

    def test_parsers_reject_missing_or_bogus_values(self):
        self.assertIsNone(sensors.parse_mac_temp("osx-cpu-temp", "0.0 °C\n"))  # Apple Silicon
        self.assertIsNone(sensors.parse_mac_temp("smctemp", ""))
        self.assertIsNone(sensors.parse_mac_temp("smctemp", None))
        self.assertIsNone(sensors.parse_mac_temp("macmon", json.dumps({"temp": {"cpu_temp_avg": None}})))
        self.assertIsNone(sensors.parse_mac_temp("macmon", json.dumps({"memory": {}})))
        self.assertIsNone(sensors.parse_mac_temp("macmon", "{not json"))
        self.assertIsNone(sensors.parse_mac_temp("macmon", "error: no sensors"))

    def reader(self, available, outputs):
        with mock.patch.object(sensors.shutil, "which", _which(*available)):
            reader = sensors.MacCpuTemp()
        with mock.patch.object(sensors.subprocess, "run", _commands(outputs)):
            return reader, reader.read()

    def test_first_tool_that_answers_wins(self):
        outputs = {"smctemp -c": "0.0\n", "osx-cpu-temp": "55.5 °C\n"}
        self.assertEqual(self.reader(["smctemp", "osx-cpu-temp"], outputs)[1], 55.5)
        outputs = {"smctemp -c": subprocess.TimeoutExpired("smctemp", 3),
                   "macmon pipe": json.dumps({"temp": {"cpu_temp_avg": 48.0}})}
        self.assertEqual(self.reader(["smctemp", "macmon"], outputs)[1], 48.0)

    def test_no_tools_installed(self):
        self.assertIsNone(self.reader([], {})[1])

    def test_waits_before_retrying_when_nothing_answered(self):
        reader, temp = self.reader(["osx-cpu-temp"], {"osx-cpu-temp": "0.0 °C\n"})
        self.assertIsNone(temp)
        run = mock.Mock(return_value=_done("50.0 °C\n"))
        with mock.patch.object(sensors.subprocess, "run", run):
            self.assertIsNone(reader.read())
        run.assert_not_called()

    def test_sensors_uses_it_on_macos(self):
        with mock.patch.object(sensors.sys, "platform", "darwin"), \
                mock.patch.object(sensors.shutil, "which", _which()):
            s = sensors.Sensors()
        self.assertIsNone(s.lhm)
        s.nvidia = mock.Mock(read=mock.Mock(return_value=None))
        s.mac_temp = mock.Mock(read=mock.Mock(return_value=58.5))
        with mock.patch.object(sensors.sys, "platform", "darwin"):
            data = s.read()
        self.assertEqual(data["cpu_temp"], 58.5)
        self.assertIsNone(data["gpu"])


if __name__ == "__main__":
    unittest.main()
