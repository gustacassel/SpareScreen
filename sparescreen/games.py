"""Which running program is the game, its name, art and icon.

A game is, in this order:
1. never anything the user marked "not a game" (PC window, kept in the config);
2. anything in the user's "my games";
3. anything running from a store's library folder (GAME_DIRS), named after its folder;
4. where FPS is set up (Windows), the full-screen app in front if PresentMon sees it
   drawing like a game (fps.AutoDetect). Once found it stays a game while it runs.

activity.py walks the processes and hands each one to GameFinder; the window in front
comes from there too, so this module doesn't talk to the OS about windows itself.
"""

from __future__ import annotations

import os
import re
import sys
from typing import TYPE_CHECKING, Callable, Optional, TypedDict, cast

import psutil

from . import icons, images
from .gameart import GameArt
from .shapes import Game, Json

if TYPE_CHECKING:
    from .config import ConfigStore
    from .fps import AutoDetect

Friendly = Callable[[str, Optional[str]], str]  # activity.friendly_name(name, exe)

# (path fragment, lowercase with "/") -> the game name is the folder right after it
GAME_DIRS = (
    "/steamapps/common/",
    "/epic games/",
    "/gog galaxy/games/",
    "/gog games/",
    "/xboxgames/",
    "/riot games/",
    "/ea games/",
    "/ubisoft game launcher/games/",
    "/battle.net/games/",
)
# Folders that live inside those places but are not games.
NOT_GAMES = {"launcher", "directxredist", "steamworks shared", "riot client", "epic online services"}
# Helper processes that run from the game folder.
HELPERS = re.compile(r"crash|report|easyanticheat|battleye|unitycrashhandler|redist|setup|launcher", re.I)

# Full-screen programs that aren't games: browsers, video players, Windows itself...
# (the user can still add any of them to "my games").
NEVER_AUTO = {
    "chrome.exe", "msedge.exe", "firefox.exe", "opera.exe", "brave.exe", "vivaldi.exe", "iexplore.exe",
    "vlc.exe", "mpc-hc64.exe", "mpc-hc.exe", "mpc-be64.exe", "potplayermini64.exe", "mpv.exe",
    "wmplayer.exe", "video.ui.exe", "microsoft.media.player.exe", "spotify.exe", "kodi.exe", "plex.exe",
    "explorer.exe", "applicationframehost.exe", "wwahost.exe", "searchhost.exe", "lockapp.exe",
    "powerpnt.exe", "mstsc.exe", "obs64.exe", "discord.exe", "steam.exe", "steamwebhelper.exe",
    "epicgameslauncher.exe", "sparescreen.exe", "sparescreen-windows-x64.exe",
}


def game_name(exe: str | None) -> str | None:
    path = (exe or "").replace("\\", "/").lower()
    for marker in GAME_DIRS:
        start = path.find(marker)
        if start < 0:
            continue
        rest = (exe or "").replace("\\", "/")[start + len(marker):]
        folder = rest.split("/", 1)[0]
        if folder and folder.lower() not in NOT_GAMES:
            return folder
    return None


def same_exe(path: str | None) -> str:
    """Paths compared the way the OS does (case-insensitive on Windows)."""
    path = os.path.normpath(path or "")
    return path.lower() if sys.platform == "win32" else path


def file_name(exe: str) -> str:
    return re.split(r"[\\/]", exe)[-1].lower()  # Windows paths too, whatever the OS running this


_own: list[str] = []


def _own_exe() -> str:
    if not _own:
        try:
            _own.append(same_exe(psutil.Process().exe()))  # the real one (a venv's python.exe is a launcher)
        except psutil.Error:
            _own.append(same_exe(sys.executable))
    return _own[0]


def system_program(exe: str) -> bool:
    """Programs that ship with Windows, and SpareScreen itself: no point offering them as games."""
    if same_exe(exe) == _own_exe() or file_name(exe).startswith("sparescreen"):
        return True
    windir = os.environ.get("WINDIR")
    return bool(windir) and same_exe(exe).startswith(same_exe(windir) + os.sep)


def never_auto(exe: str) -> bool:
    return file_name(exe) in NEVER_AUTO or system_program(exe)


class _Detected(TypedDict, total=False):
    name: str
    hwnd: Optional[int]
    icon: Optional[str]


class GameFinder:
    """One pass per reading: begin(), consider() for each process, then finish()."""

    SOURCES = {"mine": 3, "library": 2, "auto": 1}  # which wins when several programs qualify

    def __init__(self, config: ConfigStore | None = None, auto: AutoDetect | None = None,
                 art: GameArt | None = None) -> None:
        self.config = config  # ConfigStore with the user's game lists
        self.auto = auto      # fps.AutoDetect, where it can work
        self.art = art or GameArt()
        self.exe: str | None = None  # the current game's exe, for "not a game" (kept out of the data stream)
        self._found: dict[int, _Detected] = {}  # pid -> {"name", "hwnd", "icon"} of games detected automatically
        self._icons: dict[int, _Detected] = {}  # pid -> {"icon"} of "my games" (their window's icon)

    def begin(self) -> None:
        lists = self.config.games() if self.config else {"my_games": [], "not_games": []}
        self._mine: dict[str, str] = {same_exe(g["exe"]): g["name"] for g in lists["my_games"]}
        self._not_games: set[str] = {same_exe(path) for path in lists["not_games"]}
        self._best: Json | None = None
        self._seen: set[int] = set()

    def consider(self, pid: int, name: str, exe: str | None, mem: int, key: str, friendly: Friendly) -> None:
        """One running process; `friendly(name, exe)` gives its display name."""
        self._seen.add(pid)
        exe_id = same_exe(exe) if exe else None
        if exe_id in self._not_games:
            return
        title: str | None
        if exe_id in self._mine:
            title, source = self._mine[exe_id] or friendly(name, exe), "mine"
        elif pid in self._found:  # detected before: still a game in the background
            title, source = self._found[pid]["name"], "auto"
        else:
            title, source = game_name(exe), "library"
            if not title or HELPERS.search(name):
                return
        rank = (self.SOURCES[source], mem)
        if self._best is None or rank > self._best["_rank"]:
            self._best = {"name": title, "source": source, "_rank": rank, "_key": key, "pid": pid}  # pid: FPS

    def finish(self, programs: dict[str, Json], focus: str | None, focus_pid: int | None, window: Json | None,
               friendly: Friendly) -> Game | None:
        """The game (with cpu, mem, since, art and icon) or None. `programs` are the per-exe
        totals, `focus` the key of the app in front and `window` its window (or None)."""
        self._found = {pid: found for pid, found in self._found.items() if pid in self._seen}
        self._icons = {pid: found for pid, found in self._icons.items() if pid in self._seen}
        game = self._best
        if game is None and self.auto and focus in programs:
            game = self._auto_game(focus_pid, programs[focus], focus, window, friendly)
        self.exe = programs[game["_key"]]["exe"] if game else None
        if not game:
            return None
        prog = programs[game.pop("_key")]
        game.pop("_rank", None)
        game.update(cpu=round(prog["cpu"], 1), mem=prog["mem"], since=prog["since"])
        # "art" and "icon" URLs (Steam art is found by the game's folder name), and the
        # store's own name for the game when it has one (Xbox, GOG, Epic).
        art = dict(self.art.for_game(prog["exe"], game_name(prog["exe"]) or game["name"]))
        store_name = art.pop("name", None)
        if store_name and game["source"] == "library":
            game["name"] = store_name
        game.update(art)
        if game["source"] in ("auto", "mine"):
            # The window's own icon: for javaw.exe and the like, the exe's icon isn't the game's.
            game["icon"] = self._window_icon(game["pid"]) or game["icon"]
        return cast(Game, game)

    def _window_icon(self, pid: int) -> str | None:
        """Icon URL of the game's window, remembered per process once found (a game that's
        just starting may have no window yet, so it's tried again on the next reading)."""
        found = (self._found if pid in self._found else self._icons).setdefault(pid, {})
        if not found.get("icon"):
            hwnd = found.get("hwnd") or icons.main_window(pid)
            png = icons.window_icon_png(hwnd) if hwnd else None
            if png:
                found["icon"] = images.put("game-icon", png, "image/png")
        return found.get("icon")

    def _auto_game(self, pid: int | None, prog: Json, key: str, window: Json | None,
                   friendly: Friendly) -> Json | None:
        """The full-screen app in front, if PresentMon says it draws like a game."""
        assert pid is not None and self.auto is not None  # finish() checks both: it's the focused program
        exe = prog["exe"]
        if not exe or same_exe(exe) in self._not_games or never_auto(exe):
            return None
        if not window or not window["fullscreen"] or not self.auto.is_game(pid, exe):
            return None
        name = (window["title"] or friendly(prog["name"], exe))[:60]
        self._found[pid] = {"name": name, "hwnd": window.get("hwnd")}  # stays a game while it runs
        return {"name": name, "source": "auto", "_key": key, "pid": pid}
