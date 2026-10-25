"""Art, icons and names from what Xbox, GOG and Epic keep on disk (fake store folders)."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sparescreen import gameart, games, images

try:
    from PIL import Image
except ImportError:  # Pillow is only installed on Windows
    Image = None

MICROSOFT_GAME_CONFIG = """<?xml version="1.0" encoding="utf-8"?>
<Game configVersion="1">
  <ShellVisuals DefaultDisplayName="Forza Horizon 5" PublisherDisplayName="Xbox Game Studios"
                StoreLogo="StoreLogo.png" Square150x150Logo="Logo.png" Square480x480Logo="Logo480.png"
                SplashScreenImage="Assets\\Splash.png" BackgroundColor="#000000"/>
</Game>"""


class XboxTest(unittest.TestCase):
    def test_reads_the_game_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            content = Path(tmp) / "XboxGames" / "Forza Horizon 5" / "Content"
            (content / "Assets").mkdir(parents=True)
            (content / "MicrosoftGame.config").write_text(MICROSOFT_GAME_CONFIG, encoding="utf-8")
            (content / "Assets" / "Splash.png").write_bytes(b"splash")
            (content / "Logo480.scale-100.png").write_bytes(b"small")  # Store packages ship qualified copies
            (content / "Logo480.scale-200.png").write_bytes(b"the bigger one")
            visuals = gameart.xbox_visuals(content / "ForzaHorizon5.exe")
        self.assertEqual(visuals["name"], "Forza Horizon 5")
        self.assertEqual(visuals["art"].name, "Splash.png")
        self.assertEqual(visuals["logo"].name, "Logo480.scale-200.png")

    def test_appx_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            content = Path(tmp) / "XboxGames" / "Some Game" / "Content"
            content.mkdir(parents=True)
            (content / "appxmanifest.xml").write_text(
                '<Package><Applications><Application><uap:VisualElements DisplayName="Some Game" '
                'Square150x150Logo="Logo.png"><uap:SplashScreen Image="Splash.png"/></uap:VisualElements>'
                '</Application></Applications></Package>', encoding="utf-8")
            (content / "Splash.png").write_bytes(b"s")
            visuals = gameart.xbox_visuals(content / "game.exe")
        self.assertEqual((visuals["name"], visuals["art"].name, visuals["logo"]), ("Some Game", "Splash.png", None))

    def test_not_an_xbox_game(self):
        self.assertIsNone(gameart.xbox_visuals(r"C:\Games\x.exe"))


class GogTest(unittest.TestCase):
    def test_icon_and_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "GOG Galaxy" / "Games" / "The Witcher 3"
            (root / "bin").mkdir(parents=True)
            (root / "goggame-1207664663.info").write_text(json.dumps({"name": "The Witcher 3: Wild Hunt"}),
                                                          encoding="utf-8")
            (root / "goggame-1207664663.ico").write_bytes(b"ico")
            found = gameart.gog_files(root / "bin" / "witcher3.exe")
        self.assertEqual(found["name"], "The Witcher 3: Wild Hunt")
        self.assertEqual(found["ico"].name, "goggame-1207664663.ico")

    @unittest.skipIf(Image is None, "Pillow not installed")
    def test_biggest_image_of_an_ico(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "game.ico"
            Image.new("RGBA", (256, 256), (255, 0, 0, 255)).save(path, sizes=[(16, 16), (256, 256)])
            png = gameart.ico_png(path)
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(Image.open(__import__("io").BytesIO(png)).size, (256, 256))

    def test_broken_ico(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.ico"
            path.write_bytes(b"not an icon")
            self.assertIsNone(gameart.ico_png(path))


class EpicTest(unittest.TestCase):
    def test_display_name_from_the_launcher_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "ABC.item").write_text(json.dumps({
                "DisplayName": "Rocket League", "InstallLocation": "C:\\Program Files\\Epic Games\\rocketleague"}),
                encoding="utf-8")
            name = gameart.epic_name(r"C:\Program Files\Epic Games\rocketleague\Binaries\Win64\RocketLeague.exe",
                                     dirs=[tmp])
            other = gameart.epic_name(r"C:\Program Files\Epic Games\Other\x.exe", dirs=[tmp])
        self.assertEqual((name, other), ("Rocket League", None))


class GameArtStoresTest(unittest.TestCase):
    def test_xbox_game_gets_art_icon_and_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            content = Path(tmp) / "XboxGames" / "Forza Horizon 5" / "Content"
            (content / "Assets").mkdir(parents=True)
            (content / "MicrosoftGame.config").write_text(MICROSOFT_GAME_CONFIG, encoding="utf-8")
            (content / "Assets" / "Splash.png").write_bytes(b"splash")
            (content / "Logo480.png").write_bytes(b"logo")
            with mock.patch.object(gameart.icons, "exe_icon_png") as exe_icon:
                found = gameart.GameArt(roots=[]).for_game(str(content / "ForzaHorizon5.exe"), "Forza Horizon 5")
        exe_icon.assert_not_called()  # the store's logo is better than the exe's icon
        self.assertEqual(found["name"], "Forza Horizon 5")
        self.assertEqual(images.get("game-art")[0], b"splash")
        self.assertEqual(images.get("game-icon")[0], b"logo")


class FinderStoreNameTest(unittest.TestCase):
    def test_store_name_and_window_icon_for_my_games(self):
        art = mock.Mock(for_game=mock.Mock(return_value={"art": None, "icon": "art/exe", "name": "Rocket League"}))
        finder = games.GameFinder(art=art)
        programs = {"k": {"exe": r"C:\Epic Games\rocketleague\RocketLeague.exe", "cpu": 1, "mem": 1, "since": 0}}
        finder.begin()
        finder.consider(5, "RocketLeague.exe", programs["k"]["exe"], 1, "k", lambda n, e: n)
        game = finder.finish(programs, None, None, None, lambda n, e: n)
        self.assertEqual((game["name"], game["icon"]), ("Rocket League", "art/exe"))  # store name for library games

        config = mock.Mock(games=mock.Mock(return_value={"my_games": [{"exe": r"C:\mc\javaw.exe", "name": "Minecraft"}],
                                                          "not_games": []}))
        finder = games.GameFinder(config=config, art=art)
        programs = {"k": {"exe": r"C:\mc\javaw.exe", "cpu": 1, "mem": 1, "since": 0}}
        with mock.patch.object(games.icons, "main_window", return_value=42), \
                mock.patch.object(games.icons, "window_icon_png", return_value=b"block") as window_icon, \
                mock.patch.object(games.images, "put", return_value="art/window"):
            finder.begin()
            finder.consider(9, "javaw.exe", r"C:\mc\javaw.exe", 1, "k", lambda n, e: n)
            game = finder.finish(programs, None, None, None, lambda n, e: n)
        self.assertEqual((game["name"], game["icon"]), ("Minecraft", "art/window"))  # user's name, window icon
        window_icon.assert_called_once_with(42)


if __name__ == "__main__":
    unittest.main()
