"""Demo data must keep the same shape as the real sources, or the page breaks in --demo."""

import tempfile
import unittest
from unittest import mock

from sparescreen import claude
from sparescreen.activity import ActivitySource
from sparescreen.demo import DemoActivity, DemoClaude, DemoSystem
from sparescreen.sources import SystemSource


class DemoShapeTest(unittest.TestCase):
    def test_system(self):
        with mock.patch("sparescreen.sources.ram_name", return_value="16 GB"):
            real = SystemSource()
        real.sensors.nvidia.exe = None  # keep the test independent of the machine's GPU
        real_data, demo = real.read(), DemoSystem().read()
        self.assertEqual(set(demo), set(real_data))
        for key in ("cpu", "ram", "net"):
            self.assertEqual(set(demo[key]), set(real_data[key]), key)

    def test_claude(self):
        with tempfile.TemporaryDirectory() as home, mock.patch.object(claude, "load_limits", return_value=None):
            real = claude.ClaudeSource(home=home).read()
        demo = DemoClaude().read()
        self.assertEqual(set(demo), set(real))
        self.assertEqual(set(demo["today"]), set(real["today"]))
        self.assertEqual(set(demo["fable_week"]), set(real["fable_week"]))

    def test_activity(self):
        self.assertEqual(set(DemoActivity().read()), set(ActivitySource().read()))


if __name__ == "__main__":
    unittest.main()
