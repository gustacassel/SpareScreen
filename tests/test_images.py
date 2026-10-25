"""Image store, Steam game art and program icons (no real Steam or PowerShell needed)."""

import base64
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sparescreen import gameart, icons, images


class ImagesTest(unittest.TestCase):
    def test_url_version_follows_the_content(self):
        first = images.put("test-a", b"one", "image/png")
        self.assertTrue(first.startswith("art/test-a?v="))
        self.assertEqual(images.put("test-a", b"one", "image/png"), first)
        second = images.put("test-a", b"two", "image/png")
        self.assertNotEqual(second, first)
        self.assertEqual(images.get("test-a"), (b"two", "image/png"))

    def test_nothing_usable(self):
        self.assertIsNone(images.put("test-b", None, "image/png"))
        self.assertIsNone(images.put("test-b", b"x" * (images.MAX_BYTES + 1), "image/png"))
        self.assertIsNone(images.put_file("test-b", "/no/such/file.jpg"))
        self.assertIsNone(images.get("test-b"))

    def test_put_file_guesses_the_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "header.jpg"
            path.write_bytes(b"jpeg bytes")
            self.assertIsNotNone(images.put_file("test-c", path))
        self.assertEqual(images.get("test-c"), (b"jpeg bytes", "image/jpeg"))


def steam_library(root, appid="1234", folder="Hollow Peaks"):
    """A fake Steam library with one installed game and its cached art; returns the exe path."""
    steamapps = Path(root) / "steamapps"
    exe = steamapps / "common" / folder / "bin" / "game.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    (steamapps / "appmanifest_999.acf").write_text('"AppState"\n{\n\t"appid"\t\t"999"\n\t"installdir"\t\t"Other"\n}')
    (steamapps / f"appmanifest_{appid}.acf").write_text(
        f'"AppState"\n{{\n\t"appid"\t\t"{appid}"\n\t"installdir"\t\t"{folder}"\n}}')
    return exe


class GameArtTest(unittest.TestCase):
    def test_appid_from_the_manifest_in_the_same_library(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = steam_library(tmp)
            self.assertEqual(gameart.steam_appid(str(exe), "hollow peaks"), "1234")
            self.assertIsNone(gameart.steam_appid(str(exe), "Not Installed"))
        self.assertIsNone(gameart.steam_appid(r"C:\Games\Other\game.exe", "Other"))

    def test_art_prefers_wide_images_in_both_cache_layouts(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "appcache" / "librarycache"
            (cache / "1234").mkdir(parents=True)
            (cache / "1234" / "library_600x900.jpg").write_bytes(b"tall")
            self.assertEqual(gameart.steam_art("1234", [tmp]).name, "library_600x900.jpg")
            (cache / "1234_header.jpg").write_bytes(b"old layout")
            self.assertEqual(gameart.steam_art("1234", [tmp]).name, "1234_header.jpg")
            (cache / "1234" / "header.jpg").write_bytes(b"wide")
            self.assertEqual(gameart.steam_art("1234", [tmp]), cache / "1234" / "header.jpg")
            self.assertIsNone(gameart.steam_art("5678", [tmp]))

    def test_game_art_is_looked_up_once_per_game(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = steam_library(tmp)
            cache = Path(tmp) / "appcache" / "librarycache" / "1234"
            cache.mkdir(parents=True)
            (cache / "header.jpg").write_bytes(b"wide art")
            art = gameart.GameArt(roots=[])  # the game's own library is searched too
            with mock.patch.object(icons, "exe_icon_png", return_value=b"png") as icon:
                found = art.for_game(str(exe), "Hollow Peaks")
                self.assertEqual(art.for_game(str(exe), "Hollow Peaks"), found)
            icon.assert_called_once()
        self.assertTrue(found["art"].startswith("art/game-art?v="))
        self.assertTrue(found["icon"].startswith("art/game-icon?v="))
        self.assertEqual(images.get("game-art")[0], b"wide art")

    def test_games_outside_steam_get_only_the_icon(self):
        with mock.patch.object(icons, "exe_icon_png", return_value=None):
            found = gameart.GameArt(roots=[]).for_game(r"C:\XboxGames\Another Game\game.exe", "Another Game")
        self.assertEqual(found, {"art": None, "icon": None})


class IconsTest(unittest.TestCase):
    def setUp(self):
        icons._cache.clear()

    def test_other_systems_have_no_icon(self):
        with mock.patch.object(icons.sys, "platform", "linux"):
            self.assertIsNone(icons.exe_icon_png("/usr/bin/game"))

    def test_windows_icon_is_extracted_once(self):
        done = mock.Mock(returncode=0, stdout=base64.b64encode(b"\x89PNG").decode() + "\r\n")
        with mock.patch.object(icons.sys, "platform", "win32"), \
                mock.patch.object(icons.subprocess, "run", return_value=done) as run:
            self.assertEqual(icons.exe_icon_png(r"C:\Games\My Game\game.exe"), b"\x89PNG")
            self.assertEqual(icons.exe_icon_png(r"C:\Games\My Game\game.exe"), b"\x89PNG")
        run.assert_called_once()
        self.assertEqual(run.call_args.kwargs["env"]["SPARESCREEN_EXE"], r"C:\Games\My Game\game.exe")

    def test_failures_give_none(self):
        with mock.patch.object(icons.sys, "platform", "win32"), \
                mock.patch.object(icons.subprocess, "run", side_effect=OSError):
            self.assertIsNone(icons.exe_icon_png(r"C:\missing.exe"))


if __name__ == "__main__":
    unittest.main()
