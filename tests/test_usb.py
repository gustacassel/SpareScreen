import time
import unittest

from sparescreen.demo import DemoPhone
from sparescreen.usb import PhoneSource, UsbBridge, parse_battery

DUMPSYS = """Current Battery Service state:
  AC powered: false
  USB powered: true
  Wireless powered: false
  Max charging current: 500000
  status: 2
  health: 2
  present: true
  level: 78
  scale: 100
  voltage: 4231
  temperature: 325
  technology: Li-ion
"""


class ParseBatteryTest(unittest.TestCase):
    def test_parses_dumpsys(self):
        self.assertEqual(parse_battery(DUMPSYS), {
            "level": 78, "temp": 32.5, "status": "charging", "health": "good", "plugged": True})

    def test_overheat_and_odd_scale(self):
        text = DUMPSYS.replace("health: 2", "health: 3").replace("scale: 100", "scale: 50") \
                      .replace("level: 78", "level: 40").replace("USB powered: true", "USB powered: false")
        battery = parse_battery(text)
        self.assertEqual(battery["health"], "overheat")
        self.assertEqual(battery["level"], 80)
        self.assertFalse(battery["plugged"])

    def test_garbage(self):
        self.assertEqual(parse_battery("nothing here"), {
            "level": None, "temp": None, "status": "unknown", "health": "unknown", "plugged": False})


class FakeAdbBridge(UsbBridge):
    """UsbBridge with adb replaced by canned answers."""

    def __init__(self):
        super().__init__("adb", 8765, open_page=False)
        self.devices_out = "List of devices attached\nSER1 device usb:1 model:Pixel_3a transport_id:1\n\n"
        self.calls = []

    def _run(self, *args):
        self.calls.append(args)
        if args[0] == "devices":
            return self.devices_out
        if args[2:4] == ("reverse", "--list"):
            return "UsbFfs tcp:8765 tcp:8765\n"
        if args[2:] == ("shell", "dumpsys", "battery"):
            return DUMPSYS
        return ""


class BridgeBatteryTest(unittest.TestCase):
    def test_reads_battery_and_forgets_unplugged_phones(self):
        bridge = FakeAdbBridge()
        bridge._poll()
        self.assertEqual(bridge.batteries["SER1"]["model"], "Pixel 3a")
        self.assertEqual(bridge.batteries["SER1"]["temp"], 32.5)

        reads = sum(1 for c in bridge.calls if c[2:] == ("shell", "dumpsys", "battery"))
        bridge._poll()  # within BATTERY_EVERY: no new reading
        self.assertEqual(sum(1 for c in bridge.calls if c[2:] == ("shell", "dumpsys", "battery")), reads)

        bridge.batteries["SER1"]["at"] = time.time() - 3600
        bridge._poll()  # stale: read again
        self.assertEqual(sum(1 for c in bridge.calls if c[2:] == ("shell", "dumpsys", "battery")), reads + 1)

        bridge.devices_out = "List of devices attached\n\n"
        bridge._poll()
        self.assertEqual(bridge.batteries, {})

    def test_phone_source(self):
        self.assertEqual(PhoneSource(None).read(), {"devices": []})
        bridge = FakeAdbBridge()
        bridge._poll()
        (device,) = PhoneSource(bridge).read()["devices"]
        self.assertEqual(device, {"model": "Pixel 3a", "level": 78, "temp": 32.5, "status": "charging",
                                  "health": "good", "plugged": True})
        self.assertEqual(set(DemoPhone().read()["devices"][0]), set(device))  # demo keeps the same shape


if __name__ == "__main__":
    unittest.main()
