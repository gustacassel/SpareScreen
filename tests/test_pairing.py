import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from sparescreen import images
from sparescreen import pairing as pairing_module
from sparescreen.config import ConfigStore
from sparescreen.pairing import COOKIE, MAX_FAILURES, Pairing
from sparescreen.server import serve


class PairingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "devices.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_code_is_six_digits(self):
        code = Pairing(self.path).code
        self.assertEqual(len(code), 6)
        self.assertTrue(code.isdigit())

    def test_localhost_is_trusted_and_network_is_not(self):
        p = Pairing(self.path)
        self.assertTrue(p.is_trusted("127.0.0.1", None, "localhost"))
        self.assertTrue(p.is_trusted("::1", None, "[::1]"))
        # From here, but asking for another name: a website pointed at 127.0.0.1 (DNS rebinding).
        self.assertFalse(p.is_trusted("127.0.0.1", None, "evil.example"))
        self.assertFalse(p.is_trusted("127.0.0.1", None))
        self.assertFalse(p.is_trusted("192.168.0.20", None))
        self.assertFalse(Pairing(self.path, trust_localhost=False).is_trusted("127.0.0.1", None, "localhost"))

    def test_pairing_gives_a_token_that_survives_restarts(self):
        p = Pairing(self.path)
        token, error = p.pair(p.code, "Test phone")
        self.assertIsNone(error)
        cookie = f"{COOKIE}={token}"
        self.assertTrue(p.is_trusted("192.168.0.20", cookie))
        self.assertTrue(Pairing(self.path).is_trusted("192.168.0.20", cookie))  # new agent, new code
        self.assertFalse(p.is_trusted("192.168.0.20", f"{COOKIE}=forged"))
        self.assertNotIn(token, self.path.read_text(encoding="utf-8"))  # only the hash is stored

    def test_wrong_codes_lead_to_a_lockout(self):
        p = Pairing(self.path)
        wrong = "000000" if p.code != "000000" else "111111"
        for left in range(MAX_FAILURES - 1, 0, -1):
            self.assertEqual(p.pair(wrong), (None, ("wrong", left)))
        token, error = p.pair(wrong)
        self.assertEqual(error[0], "locked")
        token, error = p.pair(p.code)  # even the right code waits out the lockout
        self.assertIsNone(token)
        self.assertEqual(error[0], "locked")
        with mock.patch.object(pairing_module.time, "time", return_value=10 ** 12):
            token, error = p.pair(p.code)
        self.assertIsNotNone(token)

    def test_code_changes_after_pairing_and_lockouts_grow(self):
        p = Pairing(self.path)
        used = p.code
        p.pair(used)
        self.assertNotEqual(p.code, used)  # seen once, can't pair again later
        self.assertEqual(p.pair(used)[1][0], "wrong")
        p = Pairing(self.path)  # a fresh count of wrong codes
        lockouts = []
        for round_ in range(3):
            with mock.patch.object(pairing_module.time, "time", return_value=10 ** 12 * (round_ + 1)):
                before = p.code
                wrong = "000000" if p.code != "000000" else "111111"
                for _ in range(MAX_FAILURES):
                    error = p.pair(wrong)[1]
                lockouts.append(error[1])
                self.assertNotEqual(p.code, before)  # guesses so far are worth nothing
        self.assertEqual(lockouts, [60, 120, 240])

    def test_odd_characters_in_the_code(self):
        self.assertEqual(Pairing(self.path).pair("é1234")[1][0], "wrong")  # no crash

    def test_reset_forgets_devices(self):
        p = Pairing(self.path)
        token, _ = p.pair(p.code)
        p.reset()
        self.assertFalse(p.is_trusted("192.168.0.20", f"{COOKIE}={token}"))

    def test_malformed_cookie_is_rejected(self):
        self.assertFalse(Pairing(self.path).is_trusted("192.168.0.20", "\x00;;=;"))


class PairedServerTest(unittest.TestCase):
    """The server as seen from another device on the network (localhost not trusted)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.pairing = Pairing(Path(cls.tmp.name) / "devices.json", trust_localhost=False)
        config = ConfigStore(Path(cls.tmp.name) / "config.json")
        cls.server = serve("127.0.0.1", 0, [config], 0.2, config, cls.pairing)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def call(self, path, body=None, cookie=None):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode() if body is not None else None,
                                     method="POST" if body is not None else "GET")
        if cookie:
            req.add_header("Cookie", cookie)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, resp.headers, resp.read() if path != "/events" else resp.readline()
        except urllib.error.HTTPError as err:
            err.close()
            return err.code, err.headers, b""

    def test_page_is_public_but_data_is_not(self):
        self.assertEqual(self.call("/")[0], 200)
        self.assertEqual(self.call("/events")[0], 401)
        self.assertEqual(self.call("/config", {"theme": "neon"})[0], 401)
        # Covers and game art tell what you're doing: they need pairing too.
        self.assertEqual(self.call("/" + images.put("test-pairing", b"img", "image/png"))[0], 401)
        self.assertEqual(json.loads(self.call("/auth")[2]), {"paired": False, "pairing": True})

    def test_pair_then_access(self):
        status, _, body = self.call("/pair", {"code": "not-it"})
        self.assertEqual(status, 403)
        status, headers, _ = self.call("/pair", {"code": self.pairing.code})
        self.assertEqual(status, 200)
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertEqual(json.loads(self.call("/auth", cookie=cookie)[2])["paired"], True)
        self.assertEqual(self.call("/events", cookie=cookie)[0], 200)
        self.assertEqual(self.call("/config", {"theme": "neon"}, cookie=cookie)[0], 200)

    def test_code_is_not_handed_out(self):
        # Only the PC window (with its key) shows the code; /info doesn't, since a phone on
        # USB also arrives as this PC.
        self.assertNotIn("code", json.loads(self.call("/info")[2] or b"{}"))
        self.assertEqual(self.call("/pair-code")[0], 404)


if __name__ == "__main__":
    unittest.main()
