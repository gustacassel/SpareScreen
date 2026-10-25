"""Resting the USB phone's screen: when (PC locked, night) and how (dim or off, then back)."""

import datetime
import unittest
from unittest import mock

from sparescreen import screen
from sparescreen.config import clean
from sparescreen.usb import UsbBridge


class Config:
    def __init__(self, **values):
        self.values = dict({"usb_screen": "dim", "night_mode": "off", "night_hours": "23-7"}, **values)

    def read(self):
        return dict(self.values)


def at(hour):
    return datetime.datetime(2026, 10, 25, hour, 30)


class WhenTest(unittest.TestCase):
    def test_night_hours(self):
        self.assertTrue(screen.in_night_hours("23-7", at(23)))
        self.assertTrue(screen.in_night_hours("23-7", at(3)))
        self.assertFalse(screen.in_night_hours("23-7", at(7)))
        self.assertTrue(screen.in_night_hours("0-8", at(0)))
        self.assertFalse(screen.in_night_hours("0-8", at(12)))
        self.assertFalse(screen.in_night_hours(None, at(3)))

    def test_locked_pc_or_night_with_night_mode(self):
        self.assertEqual(screen.wanted(Config(), at(12), locked=True), "dim")
        self.assertIsNone(screen.wanted(Config(), at(12), locked=False))
        self.assertIsNone(screen.wanted(Config(), at(2), locked=False))  # night mode off
        self.assertEqual(screen.wanted(Config(night_mode="dim", usb_screen="off"), at(2), locked=False), "off")
        self.assertIsNone(screen.wanted(Config(usb_screen="keep"), at(12), locked=True))

    def test_setting_values(self):
        self.assertEqual(clean({"usb_screen": "off"}), {"usb_screen": "off"})
        self.assertEqual(clean({"usb_screen": "explode"}), {})


class FakeAdb:
    def __init__(self):
        self.calls = []
        self.settings = {"screen_brightness": "180", "screen_brightness_mode": "1"}

    def __call__(self, *args):
        self.calls.append(args)
        if args[2:6] == ("shell", "settings", "get", "system"):
            return self.settings[args[6]] + "\n"
        if args[2:6] == ("shell", "settings", "put", "system"):
            self.settings[args[6]] = args[7]
        return ""


class HowTest(unittest.TestCase):
    def bridge(self):
        bridge = UsbBridge("adb", 8765)
        bridge._run = FakeAdb()
        return bridge

    def test_dim_then_back_to_the_users_brightness(self):
        bridge = self.bridge()
        bridge._rest_screen("SER1", "dim")
        self.assertEqual(bridge._run.settings, {"screen_brightness": "1", "screen_brightness_mode": "0"})
        bridge._rest_screen("SER1", "dim")  # nothing new while it stays dimmed
        calls = len(bridge._run.calls)
        bridge._rest_screen("SER1", None)
        self.assertEqual(bridge._run.settings, {"screen_brightness": "180", "screen_brightness_mode": "1"})
        self.assertGreater(len(bridge._run.calls), calls)

    def test_off_then_wake(self):
        bridge = self.bridge()
        bridge._rest_screen("SER1", "off")
        bridge._rest_screen("SER1", None)
        keys = [c[-1] for c in bridge._run.calls if "keyevent" in c]
        self.assertEqual(keys, ["KEYCODE_SLEEP", "KEYCODE_WAKEUP"])

    def test_restore_when_closing(self):
        bridge = self.bridge()
        bridge._rest_screen("SER1", "dim")
        bridge.restore()
        self.assertEqual(bridge._run.settings["screen_brightness"], "180")
        self.assertEqual(bridge._rested, {})

    def test_poll_applies_the_rule_to_connected_phones(self):
        bridge = UsbBridge("adb", 8765, screen=lambda: "off")
        with mock.patch.object(bridge, "_devices", return_value={"SER1": ("device", "Galaxy A55")}), \
                mock.patch.object(bridge, "_ensure"), mock.patch.object(bridge, "_read_battery"), \
                mock.patch.object(bridge, "_rest_screen") as rest:
            bridge._poll()
        rest.assert_called_once_with("SER1", "off")


if __name__ == "__main__":
    unittest.main()
