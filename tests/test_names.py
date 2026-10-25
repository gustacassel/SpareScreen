"""Reaching the PC by name: candidate names and moving the pairing to another address."""

import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from sparescreen import names, pairing as pairing_module
from sparescreen.config import ConfigStore
from sparescreen.pairing import COOKIE, Pairing
from sparescreen.panel import Panel
from sparescreen.server import serve


class CandidatesTest(unittest.TestCase):
    def test_names(self):
        self.assertEqual(names.candidates("DesktopGustavo", "DesktopGustavo"),
                         ["desktopgustavo.local", "desktopgustavo"])
        self.assertEqual(names.candidates("gamer-pc", "gamer-pc.lan"), ["gamer-pc.local", "gamer-pc", "gamer-pc.lan"])

    def test_skips_names_that_are_not_valid_dns(self):
        self.assertEqual(names.candidates("My_PC", "My_PC"), [])
        self.assertEqual(names.candidates("box", "box.localdomain"), ["box.local", "box"])


class HandoffTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pairing = Pairing(Path(self.tmp.name) / "devices.json", trust_localhost=False)
        self.token, _ = self.pairing.pair(self.pairing.code, "phone", "192.168.0.20")
        self.digest = self.pairing.paired_hash(f"{COOKIE}={self.token}")

    def tearDown(self):
        self.tmp.cleanup()

    def test_code_moves_the_device_once(self):
        code = self.pairing.handoff(self.digest)
        new = self.pairing.redeem(code)
        self.assertTrue(self.pairing.is_trusted("192.168.0.20", f"{COOKIE}={new}"))
        self.assertFalse(self.pairing.is_trusted("192.168.0.20", f"{COOKIE}={self.token}"))
        self.assertIsNone(self.pairing.redeem(code))  # single use
        self.assertEqual(len(self.pairing.devices()), 1)

    def test_code_expires(self):
        code = self.pairing.handoff(self.digest)
        later = pairing_module.time.time() + pairing_module.HANDOFF_FOR + 1
        with mock.patch.object(pairing_module.time, "time", return_value=later):
            self.assertIsNone(self.pairing.redeem(code))

    def test_unknown_code(self):
        self.assertIsNone(self.pairing.redeem("made-up"))


class NamesServerTest(unittest.TestCase):
    """As seen from a phone on Wi-Fi: localhost is not trusted here."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.pairing = Pairing(Path(cls.tmp.name) / "devices.json", trust_localhost=False)
        config = ConfigStore(Path(cls.tmp.name) / "config.json")
        cls.panel = Panel(cls.pairing, local_url="http://localhost:8765")
        cls.server = serve("127.0.0.1", 0, [config], 0.2, config, cls.pairing, panel=cls.panel)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def call(self, method, path, body=None, cookie=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=5)
        headers = {"Cookie": cookie} if cookie else {}
        conn.request(method, path, json.dumps(body) if body is not None else None, headers)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, resp.headers, json.loads(data) if data.startswith(b"{") else None

    def test_whoami_is_public_and_cross_origin(self):
        status, headers, data = self.call("GET", "/whoami")
        self.assertEqual((status, data["id"]), (200, names.INSTANCE))
        self.assertEqual(headers["Access-Control-Allow-Origin"], "*")

    def test_move_to_a_name_keeps_the_pairing(self):
        self.assertEqual(self.call("GET", "/names")[0], 401)
        token, _ = self.pairing.pair(self.pairing.code, "phone")
        cookie = f"{COOKIE}={token}"
        status, _, data = self.call("GET", "/names", cookie=cookie)
        self.assertEqual((status, data["id"]), (200, names.INSTANCE))

        with mock.patch.object(names, "candidates", return_value=["mypc.local"]):
            self.call("POST", "/names/works", {"name": "mypc.local"}, cookie)
        self.assertIn("mypc.local", self.panel.reachable)

        code = self.call("POST", "/handoff", {}, cookie)[2]["code"]
        status, headers, _ = self.call("GET", f"/?handoff={code}")
        self.assertEqual((status, headers["Location"]), (302, "/"))
        new_cookie = headers["Set-Cookie"].split(";", 1)[0]
        self.assertEqual(self.call("GET", "/names", cookie=new_cookie)[0], 200)
        self.assertEqual(self.call("GET", "/names", cookie=cookie)[0], 401)  # the old address's cookie

        status, headers, _ = self.call("GET", f"/?handoff={code}")  # used already
        self.assertEqual(status, 302)
        self.assertIsNone(headers["Set-Cookie"])


if __name__ == "__main__":
    unittest.main()
