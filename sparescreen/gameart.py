"""Art for the running game: Steam's cached library images, else the .exe icon.

Steam keeps the art it shows in its library on disk, in
<Steam>/appcache/librarycache/<appid>/ (header.jpg, library_hero.jpg,
library_600x900.jpg...; older versions used flat files like <appid>_header.jpg).
The appid comes from the appmanifest_<appid>.acf whose "installdir" is the game's
folder, in the same Steam library as the game. Nothing is downloaded.
"""

import glob
import os
import re
import sys
from pathlib import Path

from . import icons, images

# Preferred first: wide images fit the game screen best.
ART_NAMES = ("header.jpg", "library_hero.jpg", "capsule_616x353.jpg", "library_600x900.jpg")
_INSTALLDIR = re.compile(r'"installdir"\s+"([^"]+)"', re.I)
_APPID = re.compile(r'"appid"\s+"(\d+)"', re.I)


def steam_roots():
    """Folders where Steam itself (and so its art cache) may be installed."""
    home = Path.home()
    roots = []
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                roots.append(Path(winreg.QueryValueEx(key, "SteamPath")[0]))
        except OSError:
            pass
        for env in ("ProgramFiles(x86)", "ProgramFiles"):
            if os.environ.get(env):
                roots.append(Path(os.environ[env]) / "Steam")
    elif sys.platform == "darwin":
        roots.append(home / "Library" / "Application Support" / "Steam")
    else:
        roots += [home / ".steam" / "steam", home / ".local" / "share" / "Steam",
                  home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam"]
    return roots


def steam_appid(exe, folder):
    """appid of the Steam game installed in `folder`, found next to its library, or None."""
    path = str(exe).replace("\\", "/")
    cut = path.lower().find("/steamapps/common/")
    if cut < 0:
        return None
    steamapps = path[:cut] + "/steamapps"
    for manifest in glob.glob(steamapps + "/appmanifest_*.acf"):
        try:
            text = Path(manifest).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        installdir = _INSTALLDIR.search(text)
        appid = _APPID.search(text)
        if installdir and appid and installdir.group(1).lower() == folder.lower():
            return appid.group(1)
    return None


def steam_art(appid, roots):
    """Path of the best cached library image for `appid`, or None."""
    for root in roots:
        cache = Path(root) / "appcache" / "librarycache"
        for name in ART_NAMES:
            for candidate in (cache / appid / name, cache / f"{appid}_{name}"):
                if candidate.is_file():
                    return candidate
    return None


class GameArt:
    """Remembers the art per game, so it's looked up once when the game starts."""

    def __init__(self, roots=None):
        self.roots = roots
        self._last = (None, {"art": None, "icon": None})

    def for_game(self, exe, folder):
        if self._last[0] == exe:
            return self._last[1]
        found = {"art": None, "icon": None}
        try:
            appid = steam_appid(exe, folder) if exe else None
            if appid:
                library = str(exe).replace("\\", "/")
                library = library[:library.lower().find("/steamapps/")]
                roots = (self.roots if self.roots is not None else steam_roots()) + [Path(library)]
                art = steam_art(appid, roots)
                found["art"] = images.put_file("game-art", art) if art else None
            png = icons.exe_icon_png(exe)
            found["icon"] = images.put("game-icon", png, "image/png") if png else None
        except Exception:  # art is a nice-to-have: never break the activity source over it
            pass
        self._last = (exe, found)
        return found
