"""Small pure functions: names, game detection, config validation, status line."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sparescreen import statusline
from sparescreen.activity import HELPERS, friendly_name, game_name
from sparescreen.config import DEFAULTS, ConfigStore, clean
from sparescreen.hwinfo import short_cpu_name, short_gpu_name


class HardwareNamesTest(unittest.TestCase):
    def test_cpu_names(self):
        self.assertEqual(short_cpu_name("AMD Ryzen 5 7600X 6-Core Processor"), "Ryzen 5 7600X")
        self.assertEqual(short_cpu_name("13th Gen Intel(R) Core(TM) i7-13700K"), "Core i7-13700K")
        self.assertEqual(short_cpu_name("Intel(R) Core(TM) i5-8250U CPU @ 1.60GHz"), "Core i5-8250U")
        self.assertEqual(short_cpu_name("Apple M2 Pro"), "Apple M2 Pro")

    def test_gpu_names(self):
        self.assertEqual(short_gpu_name("NVIDIA GeForce RTX 4070"), "RTX 4070")
        self.assertEqual(short_gpu_name("AMD Radeon RX 7800 XT"), "Radeon RX 7800 XT")
        self.assertEqual(short_gpu_name("Intel(R) UHD Graphics 770"), "UHD Graphics 770")


class GameDetectionTest(unittest.TestCase):
    def test_store_libraries(self):
        cases = {
            r"D:\SteamLibrary\steamapps\common\Hollow Peaks\bin\game.exe": "Hollow Peaks",
            r"C:\Program Files\Epic Games\Some Game\Binaries\Win64\x.exe": "Some Game",
            r"C:\XboxGames\Another Game\Content\game.exe": "Another Game",
            "/home/user/.local/share/Steam/steamapps/common/Linux Game/run": "Linux Game",
        }
        for path, name in cases.items():
            self.assertEqual(game_name(path), name, path)

    def test_not_games(self):
        self.assertIsNone(game_name(r"C:\Windows\explorer.exe"))
        self.assertIsNone(game_name(r"D:\SteamLibrary\steamapps\common\Steamworks Shared\redist.exe"))
        self.assertIsNone(game_name(None))

    def test_helper_processes(self):
        self.assertTrue(HELPERS.search("UnityCrashHandler64.exe"))
        self.assertTrue(HELPERS.search("EasyAntiCheat.exe"))
        self.assertFalse(HELPERS.search("HollowPeaks.exe"))

    def test_friendly_name_falls_back_to_process_name(self):
        self.assertEqual(friendly_name("someapp.exe", None), "someapp")


class ConfigTest(unittest.TestCase):
    def test_clean_keeps_only_valid_values(self):
        self.assertEqual(clean({"theme": "neon", "rotate": 30, "sound": False}),
                         {"theme": "neon", "rotate": 30, "sound": False})
        self.assertEqual(clean({"theme": "grafite", "rotate": 7, "sound": "yes", "other": 1}), {})
        self.assertEqual(clean("not a dict"), {})

    def test_screens_keep_order_and_need_at_least_one(self):
        self.assertEqual(clean({"screens": ["pc", "hardware", "nope"]})["screens"], ["hardware", "pc"])
        self.assertNotIn("screens", clean({"screens": []}))

    def test_fan_names_and_cpu_fan(self):
        out = clean({"fan_names": {"Fan 2": "  Radiator  ", "Fan 3": "   "}, "cpu_fan": "Fan 2"})
        self.assertEqual(out["fan_names"], {"Fan 2": "Radiator"})  # empty name = back to original
        self.assertEqual(out["cpu_fan"], "Fan 2")
        self.assertIsNone(clean({"cpu_fan": None})["cpu_fan"])

    def test_store_persists_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sub" / "config.json"
            store = ConfigStore(path)
            self.assertEqual(store.read(), DEFAULTS)
            store.update({"theme": "light", "rotate": 99})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["theme"], "light")
            again = ConfigStore(path).read()
            self.assertEqual(again["theme"], "light")
            self.assertEqual(again["rotate"], DEFAULTS["rotate"])  # invalid value ignored


class StatusLineTest(unittest.TestCase):
    def test_text(self):
        data = {"model": {"display_name": "Opus"}, "context_window": {"used_percentage": 12.4},
                "rate_limits": {"five_hour": {"used_percentage": 30}, "seven_day": {"used_percentage": 55.6}}}
        self.assertEqual(statusline.status_text(data), "Opus · ctx 12% · 5h 30% · week 56%")
        self.assertEqual(statusline.status_text({}), "Claude")

    def test_save_and_load_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(statusline, "LIMITS_FILE", Path(tmp) / "x" / "limits.json"):
                self.assertIsNone(statusline.load_limits())
                statusline.save_limits({"five_hour": {"used_percentage": 10, "resets_at": 1}})
                saved = statusline.load_limits()
        self.assertEqual(saved["rate_limits"]["five_hour"]["used_percentage"], 10)
        self.assertIn("updated_at", saved)


if __name__ == "__main__":
    unittest.main()
