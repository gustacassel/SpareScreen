"""Which program is the game: the user's lists, store folders and automatic detection."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sparescreen import activity, fps, games, panel
from sparescreen.config import ConfigStore, clean

STEAM = r"D:\SteamLibrary\steamapps\common\Hollow Peaks\game.exe"
MINE = r"C:\Games\Minecraft\javaw.exe"


class Proc:
    def __init__(self, pid, exe, mem):
        self.pid = pid
        self.info = {"name": exe.rsplit("\\", 1)[-1], "exe": exe,
                     "memory_info": mock.Mock(rss=mem), "create_time": 100.0}

    def cpu_percent(self, _):
        return 0.0


class GameListsConfigTest(unittest.TestCase):
    def test_lists_stay_on_the_pc(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ConfigStore(Path(tmp) / "config.json")
            store.set_games([{"exe": MINE, "name": "Minecraft"}], [r"C:\Tools\viewer.exe"])
            self.assertNotIn("my_games", store.read())  # the page (and the phone) never get the paths
            again = ConfigStore(Path(tmp) / "config.json").games()
        self.assertEqual(again["my_games"], [{"exe": MINE, "name": "Minecraft"}])
        self.assertEqual(again["not_games"], [r"C:\Tools\viewer.exe"])
        self.assertEqual(clean({"my_games": [{"exe": "x"}]}), {})  # not editable from POST /config


class DetectionOrderTest(unittest.TestCase):
    def detect(self, procs, my_games=(), not_games=(), auto=None, focus=None, window=None):
        config = mock.Mock(games=mock.Mock(return_value={"my_games": list(my_games), "not_games": list(not_games)}))
        source = activity.ActivitySource(config=config, auto=auto)
        source.games.art = mock.Mock(for_game=mock.Mock(return_value={"art": None, "icon": None}))
        with mock.patch.object(activity.psutil, "process_iter", return_value=procs), \
                mock.patch.object(activity, "foreground_pid", return_value=focus), \
                mock.patch.object(activity, "foreground_window", return_value=window), \
                mock.patch.object(activity, "friendly_name", side_effect=lambda name, exe: name), \
                mock.patch.object(games.icons, "main_window", return_value=None), \
                mock.patch.object(games.sys, "platform", "win32"):  # no real Windows calls on other systems
            return source.read()["game"], source

    def test_store_folder(self):
        game, source = self.detect([Proc(1, STEAM, 100)])
        self.assertEqual((game["name"], game["source"], game["pid"]), ("Hollow Peaks", "library", 1))
        self.assertEqual(source.game_exe, STEAM)

    def test_my_games_win_over_store_folders(self):
        game, _ = self.detect([Proc(1, STEAM, 900), Proc(2, MINE, 100)],
                              my_games=[{"exe": MINE.upper(), "name": "Minecraft"}])  # case doesn't matter
        self.assertEqual((game["name"], game["source"]), ("Minecraft", "mine"))

    def test_not_a_game_wins_over_everything(self):
        game, _ = self.detect([Proc(1, STEAM, 100)], not_games=[STEAM])
        self.assertIsNone(game)

    def test_automatic_for_the_full_screen_app_in_front(self):
        auto = mock.Mock(is_game=mock.Mock(return_value=True))
        window = {"title": "Minecraft 1.21", "fullscreen": True}
        game, _ = self.detect([Proc(7, MINE, 100)], auto=auto, focus=7, window=window)
        self.assertEqual((game["name"], game["source"]), ("Minecraft 1.21", "auto"))
        auto.is_game.assert_called_once_with(7, MINE)

    def test_detected_game_stays_a_game_in_the_background_with_its_window_icon(self):
        auto = mock.Mock(is_game=mock.Mock(return_value=True))
        config = mock.Mock(games=mock.Mock(return_value={"my_games": [], "not_games": []}))
        source = activity.ActivitySource(config=config, auto=auto)
        source.games.art = mock.Mock(for_game=mock.Mock(return_value={"art": None, "icon": "art/java-cup"}))
        with mock.patch.object(activity.psutil, "process_iter", return_value=[Proc(7, MINE, 100)]), \
                mock.patch.object(activity, "friendly_name", side_effect=lambda name, exe: name), \
                mock.patch.object(games.icons, "window_icon_png", return_value=b"png") as window_icon, \
                mock.patch.object(games.images, "put", return_value="art/game-icon?v=1"), \
                mock.patch.object(games.sys, "platform", "win32"):
            window = {"title": "Minecraft 1.21", "fullscreen": True, "hwnd": 99}
            with mock.patch.object(activity, "foreground_pid", return_value=7), \
                    mock.patch.object(activity, "foreground_window", return_value=window):
                self.assertEqual(source.read()["game"]["icon"], "art/game-icon?v=1")  # the window's, not Java's
            source._at = 0
            with mock.patch.object(activity, "foreground_pid", return_value=None), \
                    mock.patch.object(activity, "foreground_window", return_value=None):
                game = source.read()["game"]  # alt-tabbed out: still the game
        self.assertEqual((game["name"], game["source"]), ("Minecraft 1.21", "auto"))
        window_icon.assert_called_once_with(99)

    def test_no_automatic_check_for_windows_browsers_or_not_full_screen(self):
        auto = mock.Mock(is_game=mock.Mock(return_value=True))
        game, _ = self.detect([Proc(7, MINE, 100)], auto=auto, focus=7, window={"title": "x", "fullscreen": False})
        self.assertIsNone(game)
        edge = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
        game, _ = self.detect([Proc(8, edge, 100)], auto=auto, focus=8, window={"title": "Video", "fullscreen": True})
        self.assertIsNone(game)
        auto.is_game.assert_not_called()


class AutoDetectTest(unittest.TestCase):
    def test_steady_frames_mean_a_game(self):
        header = "Application,ProcessID,MsBetweenPresents\n"
        self.assertTrue(fps.AutoDetect.looks_like_a_game(header + "g,1,16.6\n" * 240))   # 60 FPS for 4 s
        self.assertFalse(fps.AutoDetect.looks_like_a_game(header + "g,1,16.6\n" * 20))   # a few frames
        self.assertFalse(fps.AutoDetect.looks_like_a_game(header + "g,1,100\n" * 80))    # 10 FPS
        self.assertFalse(fps.AutoDetect.looks_like_a_game(""))

    def test_answers_are_remembered(self):
        detect = fps.AutoDetect()
        with mock.patch.object(fps.AutoDetect, "ready", return_value=True), \
                mock.patch.object(fps.threading, "Thread") as thread:
            self.assertFalse(detect.is_game(1, "game.exe"))  # unknown yet: checks in the background
            thread.assert_called_once()
            detect._busy = False
            detect._verdicts["game.exe"] = (True, 0)
            self.assertTrue(detect.is_game(1, "game.exe"))
            detect._verdicts["menu.exe"] = (False, fps.time.time())
            self.assertFalse(detect.is_game(2, "menu.exe"))
            self.assertEqual(thread.call_count, 1)  # neither asked again

    def test_not_set_up(self):
        with mock.patch.object(fps.AutoDetect, "ready", return_value=False), \
                mock.patch.object(fps.threading, "Thread") as thread:
            self.assertFalse(fps.AutoDetect().is_game(1, "game.exe"))
        thread.assert_not_called()


class PanelGamesTest(unittest.TestCase):
    def test_add_and_not_a_game(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ConfigStore(Path(tmp) / "config.json")
            source = mock.Mock(running=[{"exe": MINE, "name": "Minecraft 1.21"}], game_exe=STEAM)
            p = panel.Panel(config=store, activity=source)
            self.assertEqual(p.games({})["running"], source.running)
            p.act("game_add", {"exe": MINE, "name": "Minecraft"})
            self.assertEqual(store.games()["my_games"], [{"exe": MINE, "name": "Minecraft"}])
            self.assertEqual(p.games({})["running"], [])  # listed ones aren't offered again
            p.act("not_game_add")  # on the game being shown
            self.assertEqual(store.games()["not_games"], [STEAM])
            p.act("not_game_add", {"exe": MINE})  # moves it from "my games" to "never"
            self.assertEqual(store.games(), {"my_games": [], "not_games": [STEAM, MINE]})
            p.act("not_game_remove", {"exe": STEAM})
            self.assertEqual(store.games()["not_games"], [MINE])


if __name__ == "__main__":
    unittest.main()
