import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from sparescreen.config import ConfigStore
from sparescreen.server import serve


class StaticSource:
    name = "static"

    def read(self):
        return {"answer": 42}


class FailingSource:
    name = "broken"

    def read(self):
        raise RuntimeError("sensor exploded")


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.config = ConfigStore(Path(cls.tmp.name) / "config.json")
        sources = [StaticSource(), FailingSource(), cls.config]
        cls.server = serve("127.0.0.1", 0, sources, 0.2, cls.config)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def get(self, path):
        return urllib.request.urlopen(self.base + path, timeout=5)

    def test_serves_the_page(self):
        with self.get("/") as resp:
            self.assertIn("text/html", resp.headers["Content-Type"])
            self.assertIn(b"app.html", resp.read())
        with self.get("/app.js") as resp:
            self.assertIn("javascript", resp.headers["Content-Type"])

    def test_no_files_outside_the_web_folder(self):
        for path in ("/../server.py", "/..%2Fserver.py", "/missing.html"):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self.get(path)
            ctx.exception.close()
            self.assertEqual(ctx.exception.code, 404, path)

    def test_events_stream_carries_every_source(self):
        with self.get("/events") as resp:
            self.assertEqual(resp.headers["Content-Type"], "text/event-stream")
            while True:
                line = resp.readline()
                if line.startswith(b"data: "):
                    break
        data = json.loads(line[6:])
        self.assertEqual(data["static"], {"answer": 42})
        self.assertEqual(data["broken"], {"error": "sensor exploded"})  # one bad source doesn't stop the rest
        self.assertIn("theme", data["config"])
        self.assertIn("time", data)

    def test_post_config(self):
        req = urllib.request.Request(self.base + "/config", data=json.dumps({"theme": "neon"}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(json.loads(resp.read())["theme"], "neon")
        self.assertEqual(self.config.read()["theme"], "neon")

    def test_post_rejects_bad_json(self):
        req = urllib.request.Request(self.base + "/config", data=b"{oops", method="POST")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)
        ctx.exception.close()
        self.assertEqual(ctx.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
