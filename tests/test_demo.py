"""Demo data must keep the same shape as the real sources, or the page breaks in --demo."""

import os
import tempfile
import unittest
from unittest import mock

from sparescreen import claude
from sparescreen.activity import ActivitySource
from sparescreen.codex import CodexSource
from sparescreen.demo import DemoActivity, DemoClaude, DemoCodex, DemoSystem
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

    def test_ai_tools(self):
        with tempfile.TemporaryDirectory() as home, mock.patch.object(claude, "load_limits", return_value=None):
            os.mkdir(os.path.join(home, "sessions"))
            real = {"claude": claude.ClaudeSource(home=home).read(), "codex": CodexSource(home=home).read()}
        for name, demo in (("claude", DemoClaude().read()), ("codex", DemoCodex().read())):
            self.assertEqual(set(demo), set(real[name]), name)
            self.assertEqual(set(demo["today"]), set(real[name]["today"]), name)

    def test_activity(self):
        self.assertEqual(set(DemoActivity().read()), set(ActivitySource().read()))
        with mock.patch("sparescreen.demo.time.time", return_value=DemoActivity.CYCLE * 1000 + 1):
            game = DemoActivity().read()["game"]
        self.assertEqual(set(game), {"name", "cpu", "mem", "since", "art", "icon", "pid"})


if __name__ == "__main__":
    unittest.main()
