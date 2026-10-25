"""The PC window: one paired device at a time, checks, device list, LibreHardwareMonitor setup."""

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from sparescreen import appwindow, lhm, panel
from sparescreen.config import ConfigStore
from sparescreen.pairing import Pairing
from sparescreen.server import serve

ANDROID = "Mozilla/5.0 (Linux; Android 14; SM-A556E) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Mobile Safari/537.36"
REDUCED = "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Mobile Safari/537.36"


class SingleDeviceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pairing = Pairing(Path(self.tmp.name) / "devices.json", trust_localhost=False)

    def tearDown(self):
        self.tmp.cleanup()

    def test_new_device_replaces_the_old_one(self):
        first, _ = self.pairing.pair(self.pairing.code, ANDROID, "192.168.0.20")
        second, _ = self.pairing.pair(self.pairing.code, REDUCED, "192.168.0.30")
        self.assertFalse(self.pairing.is_trusted("192.168.0.20", f"sparescreen_token={first}"))
        self.assertTrue(self.pairing.is_trusted("192.168.0.30", f"sparescreen_token={second}"))
        self.assertEqual([d["address"] for d in self.pairing.devices()], ["192.168.0.30"])

    def test_waiting_device_until_it_pairs(self):
        self.pairing.note_waiting("192.168.0.20", ANDROID)
        self.assertEqual(self.pairing.waiting()["address"], "192.168.0.20")
        self.pairing.pair(self.pairing.code, ANDROID, "192.168.0.20")
        self.assertIsNone(self.pairing.waiting())

    def test_remove_one(self):
        self.pairing.single = False
        self.pairing.pair(self.pairing.code, ANDROID)
        self.pairing.pair(self.pairing.code, REDUCED)
        self.pairing.remove(0)
        self.assertEqual(len(self.pairing.devices()), 1)
        self.pairing.remove(5)  # out of range: nothing happens
        self.assertEqual(len(self.pairing.devices()), 1)


class DescribeAgentTest(unittest.TestCase):
    def test_names(self):
        self.assertEqual(panel.describe_agent(ANDROID), "Android (SM-A556E) · Chrome")
        self.assertEqual(panel.describe_agent(REDUCED), "Android · Chrome")  # modern Chrome hides the model
        self.assertEqual(panel.describe_agent("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Safari/604.1"),
                         "iPhone · Safari")
        self.assertEqual(panel.describe_agent(""), "Device")


class FakeBridge:
    phones = {"R58N": "Galaxy A55"}
    batteries = {"R58N": {"level": 80, "temp": 31.0}}


class PanelTest(unittest.TestCase):
    def test_devices(self):
        p = panel.Panel(bridge=FakeBridge())
        devices = p.devices([{"address": "127.0.0.1", "local": True, "agent": ANDROID, "since": 0},
                             {"address": "127.0.0.1", "local": True, "agent": "Windows Edg/130", "since": 0},
                             {"address": "192.168.0.20", "local": False, "agent": REDUCED, "since": 0}])
        self.assertEqual([d["kind"] for d in devices["open"]], ["usb", "pc", "wifi"])
        self.assertEqual(devices["usb"], [{"model": "Galaxy A55", "level": 80, "temp": 31.0}])

    def test_sensor_check_on_windows(self):
        p = panel.Panel()
        with mock.patch.object(panel.sys, "platform", "win32"), \
                mock.patch.object(panel.lhm, "find", return_value=None):
            check = p._sensors_check({"cpu": {"temp": None}})
        self.assertEqual((check["status"], check["action"]["id"]), ("error", "lhm_install"))
        with mock.patch.object(panel.sys, "platform", "win32"), \
                mock.patch.object(panel.lhm, "find", return_value="C:/lhm.exe"), \
                mock.patch.object(panel.lhm, "running", return_value=False):
            check = p._sensors_check({"cpu": {"temp": None}})
        self.assertEqual((check["status"], check["action"]["id"]), ("warn", "lhm_start"))
        with mock.patch.object(panel.sys, "platform", "win32"):
            self.assertEqual(p._sensors_check({"cpu": {"temp": 50.0}})["status"], "ok")

    def test_usb_checks(self):
        self.assertEqual(panel.Panel(usb=False)._usb_check()["status"], "info")
        self.assertEqual(panel.Panel(bridge=FakeBridge())._usb_check()["detail"], "Connected: Galaxy A55")
        with mock.patch.object(panel.shutil, "which", return_value=None):
            self.assertEqual(panel.Panel()._usb_check()["status"], "warn")

    def test_unknown_action(self):
        self.assertEqual(panel.Panel().act("format-c"), {"ok": False})


class PanelServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.pairing = Pairing(Path(cls.tmp.name) / "devices.json")
        config = ConfigStore(Path(cls.tmp.name) / "config.json")
        cls.panel = panel.Panel(cls.pairing, info={"version": "test"}, local_url="http://localhost")
        cls.server = serve("127.0.0.1", 0, [config], 0.2, config, cls.pairing, panel=cls.panel)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def call(self, path, body=None, headers=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", headers=headers or {},
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read() or b"null")
        except urllib.error.HTTPError as err:
            err.close()
            return err.code, None

    def test_state_for_this_pc(self):
        status, state = self.call("/panel/state")
        self.assertEqual(status, 200)
        self.assertEqual(state["code"], self.pairing.code)
        self.assertIn("checks", state)

    def test_other_hostnames_and_sites_are_refused(self):
        # DNS rebinding: a page on another name that points at 127.0.0.1.
        self.assertEqual(self.call("/panel/state", headers={"Host": f"evil.example:{self.port}"})[0], 403)
        self.assertEqual(self.call("/panel/events", headers={"Host": f"evil.example:{self.port}"})[0], 403)
        # Another site's page posting to this PC through the browser.
        self.assertEqual(self.call("/panel/action", {"action": "unpair", "index": 0},
                                   {"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.call("/config", {"theme": "neon"}, {"Origin": "https://evil.example"})[0], 403)

    def test_action(self):
        with mock.patch.object(panel.webbrowser, "open") as opened:
            status, result = self.call("/panel/action", {"action": "dashboard"},
                                       {"Origin": f"http://127.0.0.1:{self.port}"})
        self.assertEqual((status, result["ok"]), (200, True))
        opened.assert_called_once_with("http://localhost")


class LibreHardwareMonitorConfigTest(unittest.TestCase):
    def test_turns_on_the_web_server_and_keeps_the_rest(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "LibreHardwareMonitor.exe"
            (Path(tmp) / "LibreHardwareMonitor.config").write_text(
                '<?xml version="1.0" encoding="utf-8"?><configuration><appSettings>'
                '<add key="runWebServerMenuItem" value="false" /><add key="listenerPort" value="8090" />'
                '<add key="theme" value="dark" /></appSettings></configuration>', encoding="utf-8")
            self.assertTrue(lhm.enable_web_server(exe))
            settings = lhm.read_settings(exe)
            self.assertEqual(settings["runWebServerMenuItem"], "true")
            self.assertEqual(settings["startMinMenuItem"], "true")
            self.assertEqual(settings["theme"], "dark")
            self.assertEqual(lhm.port(exe), 8090)

    def test_creates_a_config_when_there_is_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "LibreHardwareMonitor.exe"
            self.assertTrue(lhm.enable_web_server(exe))
            self.assertEqual(lhm.read_settings(exe)["runWebServerMenuItem"], "true")
            self.assertEqual(lhm.port(exe), lhm.DEFAULT_PORT)


class AppWindowTest(unittest.TestCase):
    def test_command(self):
        cmd = appwindow.command("edge", "http://localhost:8765/panel.html")
        self.assertEqual(cmd[:2], ["edge", "--app=http://localhost:8765/panel.html"])

    def test_falls_back_to_the_browser(self):
        with mock.patch.object(appwindow, "find_browser", return_value=None), \
                mock.patch.object(appwindow.webbrowser, "open") as opened:
            self.assertFalse(appwindow.open_window("http://localhost:8765/panel.html"))
        opened.assert_called_once()


if __name__ == "__main__":
    unittest.main()
