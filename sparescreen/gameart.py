"""Art, icon and proper name for the running game, from what the stores keep on disk.

- Steam: its cached library images (below).
- Xbox / Game Pass: the game's MicrosoftGame.config (or appxmanifest.xml) names its splash
  screen, logos and display name.
- GOG: goggame-<id>.ico (the icon, up to 256 px) and goggame-<id>.info (the name).
- Epic: its launcher manifests give the display name (the art isn't kept in a readable form).
- Anything else: the icon inside the .exe.

Steam keeps the art it shows in its library on disk, in
<Steam>/appcache/librarycache/<appid>/. The layout changes between Steam versions:
newer ones put each image in a folder named by a hash (<hash>/library_hero.jpg),
older ones keep header.jpg, library_600x900.jpg... directly in the folder, and
very old ones use flat files like <appid>_header.jpg. All three are searched.
The appid comes from the appmanifest_<appid>.acf whose "installdir" is the game's
folder, in the same Steam library as the game. Nothing is downloaded.
"""

from __future__ import annotations

import glob
import io
import json
import os
import re
import sys
from pathlib import Path
from typing import Iterable, Optional, TypedDict, cast

from . import icons, images
from .shapes import Art

# Preferred first: wide images without the title on them fit the game screen best
# (the name is shown below the art anyway, and the art gets cropped in landscape).
ART_NAMES = ("library_hero.jpg", "header.jpg", "library_header.jpg", "capsule_616x353.jpg",
             "library_capsule.jpg", "library_600x900.jpg")
_INSTALLDIR = re.compile(r'"installdir"\s+"([^"]+)"', re.I)
_APPID = re.compile(r'"appid"\s+"(\d+)"', re.I)


class _Xbox(TypedDict):
    name: Optional[str]
    art: Optional[Path]
    logo: Optional[Path]


class _Gog(TypedDict):
    name: Optional[str]
    ico: Optional[Path]


def steam_roots() -> list[Path]:
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


def steam_appid(exe: str, folder: str) -> str | None:
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


def steam_art(appid: str, roots: Iterable[str | os.PathLike[str]]) -> Path | None:
    """Path of the best cached library image for `appid`, or None."""
    for root in roots:
        cache = Path(root) / "appcache" / "librarycache"
        for name in ART_NAMES:
            candidates = [cache / appid / name, cache / f"{appid}_{name}"]
            candidates += sorted((cache / appid).glob("*/" + name))  # newer Steam: <hash>/<name>
            for candidate in candidates:
                if candidate.is_file():
                    return candidate
    return None


def _game_root(exe: str, marker: str) -> Path | None:
    """The game's own folder: the one right after `marker` ("/xboxgames/"...) in its path."""
    path = str(exe).replace("\\", "/")
    start = path.lower().find(marker)
    if start < 0:
        return None
    folder = path[start + len(marker):].split("/", 1)[0]
    return Path(path[:start + len(marker)] + folder) if folder else None


def _attribute(text: str, name: str) -> str | None:
    match = re.search(r'\b' + re.escape(name) + r'="([^"]+)"', text)
    return match.group(1) if match else None


def _image_file(folder: Path, relative: str | None) -> Path | None:
    """An image named in a manifest; Store packages often only ship qualified copies
    (Logo.scale-200.png, Logo.targetsize-256.png...), so take the biggest one."""
    if not relative:
        return None
    path = Path(folder, *re.split(r"[\\/]", relative.strip()))
    variants = [path] + [Path(p) for p in glob.glob(glob.escape(str(path.with_suffix(""))) + ".*" + path.suffix)
                         if "contrast" not in p.lower()]
    variants = [p for p in variants if p.is_file()]
    return max(variants, key=lambda p: p.stat().st_size) if variants else None


def xbox_visuals(exe: str) -> _Xbox | None:
    """Xbox / Game Pass games describe themselves in Content/MicrosoftGame.config (or a
    Store appxmanifest.xml): proper name, splash screen (wide art) and logos."""
    root = _game_root(exe, "/xboxgames/")
    if not root:
        return None
    content = root / "Content"
    for manifest in (content / "MicrosoftGame.config", content / "appxmanifest.xml"):
        try:
            text = manifest.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        splash = re.search(r'<[\w:]*SplashScreen\b[^>]*\bImage="([^"]+)"', text)
        logo = next((_attribute(text, name) for name in ("Square480x480Logo", "Square150x150Logo", "StoreLogo")
                     if _attribute(text, name)), None)
        return {
            "name": _attribute(text, "DefaultDisplayName") or _attribute(text, "DisplayName"),
            "art": _image_file(content, _attribute(text, "SplashScreenImage") or (splash and splash.group(1))),
            "logo": _image_file(content, logo),
        }
    return None


def gog_files(exe: str) -> _Gog | None:
    """GOG games keep goggame-<id>.ico (up to 256 px) and goggame-<id>.info (with the name)."""
    root = _game_root(exe, "/gog galaxy/games/") or _game_root(exe, "/gog games/")
    if not root:
        return None
    found: _Gog = {"name": None, "ico": next(iter(sorted(root.glob("goggame-*.ico"))), None)}
    for info in sorted(root.glob("goggame-*.info")):
        try:
            found["name"] = json.loads(info.read_text(encoding="utf-8", errors="replace")).get("name")
            break
        except (OSError, ValueError):
            continue
    return found


def epic_manifest_dirs() -> list[Path]:
    if sys.platform == "win32":
        return [Path(os.environ.get("ProgramData", "C:/ProgramData"), "Epic", "EpicGamesLauncher", "Data", "Manifests")]
    if sys.platform == "darwin":
        return [Path.home() / "Library" / "Application Support" / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"]
    return []


def epic_name(exe: str, dirs: Iterable[str | os.PathLike[str]] | None = None) -> str | None:
    """The proper name of an Epic game (its folders are often like "RocketLeague")."""
    path = str(exe).replace("\\", "/").lower()
    for folder in (epic_manifest_dirs() if dirs is None else dirs):
        for item in sorted(Path(folder).glob("*.item")):
            try:
                data = json.loads(item.read_text(encoding="utf-8", errors="replace"))
            except (OSError, ValueError):
                continue
            location = str(data.get("InstallLocation") or "").replace("\\", "/").rstrip("/").lower()
            if location and path.startswith(location + "/") and data.get("DisplayName"):
                return cast(str, data["DisplayName"])
    return None


def ico_png(path: str | os.PathLike[str]) -> bytes | None:
    """The biggest image in an .ico file, as PNG bytes (needs Pillow; None without it)."""
    try:
        from PIL import Image

        with Image.open(path) as ico:
            if ico.info.get("sizes"):
                ico.size = max(ico.info["sizes"])
            out = io.BytesIO()
            ico.convert("RGBA").save(out, "PNG")
            return out.getvalue()
    except Exception:  # Pillow missing (it's installed on Windows) or a broken file
        return None


class GameArt:
    """Remembers the art per game, so it's looked up once when the game starts.

    for_game() gives {"art", "icon"} URLs, plus "name" when the store knows a better one
    than the folder (Xbox, GOG, Epic)."""

    def __init__(self, roots: list[str | os.PathLike[str]] | None = None) -> None:
        self.roots = roots
        self._last: tuple[str | None, Art] = (None, {"art": None, "icon": None, "name": None})

    def for_game(self, exe: str | None, folder: str) -> Art:
        if self._last[0] == exe:
            return self._last[1]
        found: Art = {"art": None, "icon": None, "name": None}
        try:
            art = icon_png = icon_file = None
            appid = steam_appid(exe, folder) if exe else None
            if appid:
                library = str(exe).replace("\\", "/")
                library = library[:library.lower().find("/steamapps/")]
                roots = (self.roots if self.roots is not None else steam_roots()) + [Path(library)]
                art = steam_art(appid, roots)
            elif exe:
                xbox = xbox_visuals(exe)
                gog = None if xbox else gog_files(exe)
                if xbox:
                    art, icon_file, found["name"] = xbox["art"], xbox["logo"], xbox["name"]
                elif gog:
                    icon_png = ico_png(gog["ico"]) if gog["ico"] else None
                    found["name"] = gog["name"]
                else:
                    found["name"] = epic_name(exe)
            found["art"] = images.put_file("game-art", art) if art else None
            if icon_file:
                found["icon"] = images.put_file("game-icon", icon_file)
            if not found["icon"]:
                png = icon_png or icons.exe_icon_png(exe)
                found["icon"] = images.put("game-icon", png, "image/png") if png else None
        except Exception:  # art is a nice-to-have: never break the activity source over it
            pass
        self._last = (exe, found)
        return found
