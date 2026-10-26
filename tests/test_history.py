"""The last minutes kept for the page's small charts, and GET /history."""

import json
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path

from sparescreen import history
from sparescreen.config import ConfigStore
from sparescreen.server import serve


def snapshot(t, cpu=10.0, temp=50.0, gpu=None, down=1000.0):
    system = {"cpu": {"percent": cpu, "temp": temp}, "ram": {"percent": 40.0},
              "net": {"down": down, "up": 100.0}, "gpu": gpu}
    return {"time": t, "system": system}


class HistoryTest(unittest.TestCase):
    def test_one_point_per_step_averaging_the_readings(self):
        h = history.History()
        h.add(snapshot(1000, cpu=10))
        h.add(snapshot(1001, cpu=30))
        h.add(snapshot(1002, cpu=50))  # a step later: the average of 30 and 50
        data = h.read()
        cpu = data["series"].index("cpu") + 1
        self.assertEqual([p[0] for p in data["points"]], [1000, 1002])
        self.assertEqual([p[cpu] for p in data["points"]], [10, 40])

    def test_missing_values_and_no_gpu(self):
        h = history.History()
        h.add(snapshot(1000, temp=None, gpu={"percent": True}))  # a bool is not a reading
        point = dict(zip(["time"] + h.read()["series"], h.read()["points"][0]))
        self.assertIsNone(point["cpu_temp"])
        self.assertIsNone(point["gpu"])
        self.assertIsNone(point["gpu_temp"])
        self.assertEqual(point["net_down"], 1000)

    def test_keeps_only_the_window(self):
        h = history.History()
        for t in range(0, history.WINDOW + 60, history.STEP):
            h.add(snapshot(t))
        points = h.read()["points"]
        self.assertGreaterEqual(points[0][0], points[-1][0] - history.WINDOW)
        self.assertLessEqual(len(points), history.WINDOW // history.STEP + 1)

    def test_ignores_snapshots_without_time(self):
        h = history.History()
        h.add({"system": {}})
        self.assertEqual(h.read()["points"], [])


class HistoryEndpointTest(unittest.TestCase):
    def test_served_to_the_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = ConfigStore(Path(tmp) / "config.json")
            server = serve("127.0.0.1", 0, [config], 0.05, config)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                time.sleep(0.2)
                url = f"http://127.0.0.1:{server.server_address[1]}/history"
                with urllib.request.urlopen(url, timeout=5) as resp:
                    data = json.load(resp)
            finally:
                server.shutdown()
                server.server_close()
        self.assertEqual(data["window"], history.WINDOW)
        self.assertEqual(data["series"][0], "cpu")
        self.assertTrue(data["points"])  # the sampler already added one
        self.assertEqual(len(data["points"][0]), len(data["series"]) + 1)


if __name__ == "__main__":
    unittest.main()
