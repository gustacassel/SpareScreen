"""What is running on the PC: open game, focused program and the heaviest processes.

A game is detected by its executable path: anything running from inside the store
library folders (Steam, Epic, GOG, Xbox, Riot, EA, Ubisoft...). The game name is
the folder name, which in these stores is usually the pretty name.

The focused program comes from the OS: user32 on Windows; on Linux xdotool/xprop
(X11) or swaymsg/hyprctl (Sway/Hyprland, the Wayland desktops that allow it);
`lsappinfo` on macOS. Anything else just shows no focused program.
"""

import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import time

import psutil

from .gameart import GameArt

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


def game_name(exe):
    path = (exe or "").replace("\\", "/").lower()
    for marker in GAME_DIRS:
        start = path.find(marker)
        if start < 0:
            continue
        rest = exe.replace("\\", "/")[start + len(marker):]
        folder = rest.split("/", 1)[0]
        if folder and folder.lower() not in NOT_GAMES:
            return folder
    return None


# ---- Friendly program name (Windows: the .exe "File description") -----------

_descriptions = {}


def _file_description(exe):
    """'C:/.../chrome.exe' -> 'Google Chrome', read from the executable's version resource."""
    version = ctypes.windll.version
    size = version.GetFileVersionInfoSizeW(exe, None)
    if not size:
        return None
    buf = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(exe, 0, size, buf):
        return None
    ptr, length = ctypes.c_void_p(), ctypes.c_uint()
    if not version.VerQueryValueW(buf, "\\VarFileInfo\\Translation", ctypes.byref(ptr), ctypes.byref(length)) \
            or length.value < 4:
        return None
    lang, codepage = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_uint16 * 2)).contents
    key = f"\\StringFileInfo\\{lang:04x}{codepage:04x}\\FileDescription"
    if not version.VerQueryValueW(buf, key, ctypes.byref(ptr), ctypes.byref(length)) or not length.value:
        return None
    # Some files report a length past the end of the text: stop at the first null.
    return ctypes.wstring_at(ptr.value, length.value).split("\x00", 1)[0].strip() or None


def friendly_name(name, exe):
    key = exe or name
    if key not in _descriptions:
        desc = None
        if sys.platform == "win32" and exe:
            try:
                desc = _file_description(exe)
            except (OSError, AttributeError, ValueError):
                desc = None
        elif sys.platform != "win32" and exe and name and name.islower():
            # Linux process names are usually the lowercase binary ('firefox' -> 'Firefox').
            desc = name[:1].upper() + name[1:]
        _descriptions[key] = desc or os.path.splitext(name or "?")[0]
    return _descriptions[key]


# ---- Focused window ----------------------------------------------------------

def _run(args):
    """stdout of a quick helper command, or None if it is missing, slow or fails."""
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=1)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return result.stdout if result.returncode == 0 else None


def _pid(value):
    """A real PID or None (helpers report 0 or -1 when nothing has focus)."""
    try:
        pid = int(value)
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


def _windows_foreground_pid():
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value or None


def _x11_foreground_pid():
    xdotool = shutil.which("xdotool")
    if xdotool:
        pid = _pid((_run([xdotool, "getactivewindow", "getwindowpid"]) or "").strip())
        if pid:
            return pid
    xprop = shutil.which("xprop")
    if not xprop:
        return None
    # '_NET_ACTIVE_WINDOW(WINDOW): window id # 0x3a00007'; 0x0 when nothing has focus
    match = re.search(r"0x[0-9a-fA-F]+", _run([xprop, "-root", "_NET_ACTIVE_WINDOW"]) or "")
    if not match or int(match.group(), 16) == 0:
        return None
    # '_NET_WM_PID(CARDINAL) = 12345'; '_NET_WM_PID:  not found.' for windows that don't say
    match = re.search(r"=\s*(\d+)", _run([xprop, "-id", match.group(), "_NET_WM_PID"]) or "")
    return _pid(match.group(1)) if match else None


def _sway_focused(node):
    """Focused window in `swaymsg -t get_tree`, searching tiled and floating windows."""
    if node.get("focused") and _pid(node.get("pid")):
        return _pid(node["pid"])
    for child in (node.get("nodes") or []) + (node.get("floating_nodes") or []):
        pid = _sway_focused(child)
        if pid:
            return pid
    return None


def _wayland_foreground_pid():
    """Wayland hides other apps' windows on purpose; only some compositors tell us via their CLI."""
    try:
        if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") and shutil.which("hyprctl"):
            data = json.loads(_run([shutil.which("hyprctl"), "activewindow", "-j"]) or "{}")
            return _pid(data.get("pid"))
        if os.environ.get("SWAYSOCK") and shutil.which("swaymsg"):
            return _sway_focused(json.loads(_run([shutil.which("swaymsg"), "-t", "get_tree"]) or "{}"))
    except (ValueError, TypeError, AttributeError):
        pass
    return None


def _mac_foreground_pid():
    # lsappinfo ships with macOS and, unlike AppleScript/System Events, needs no Automation permission.
    lsappinfo = shutil.which("lsappinfo")
    if not lsappinfo:
        return None
    front = (_run([lsappinfo, "front"]) or "").strip()  # 'ASN:0x0-0x1d01d:'
    if not front.startswith("ASN:"):
        return None
    match = re.search(r'"pid"\s*=\s*(\d+)', _run([lsappinfo, "info", "-only", "pid", front]) or "")
    return _pid(match.group(1)) if match else None


def _windows_foreground_window():
    from ctypes import wintypes

    class MonitorInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    kind = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(hwnd, kind, 64)
    if kind.value in ("Progman", "WorkerW", "Shell_TrayWnd"):  # the desktop and the taskbar
        return None
    title = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, title, 256)
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    info = MonitorInfo(cbSize=ctypes.sizeof(MonitorInfo))
    user32.GetMonitorInfoW(user32.MonitorFromWindow(hwnd, 2), ctypes.byref(info))  # 2: nearest monitor
    screen = info.rcMonitor
    fullscreen = (rect.left <= screen.left and rect.top <= screen.top
                  and rect.right >= screen.right and rect.bottom >= screen.bottom)
    return {"title": title.value.strip(), "fullscreen": fullscreen}


def foreground_window():
    """{"title", "fullscreen"} of the window in front (Windows), else None."""
    if sys.platform != "win32":
        return None
    try:
        return _windows_foreground_window()
    except (OSError, AttributeError, ValueError):
        return None


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


def _file_name(exe):
    return re.split(r"[\\/]", exe)[-1].lower()  # Windows paths too, whatever the OS running this


def _never_auto(exe):
    return _file_name(exe) in NEVER_AUTO or _system_program(exe)


_own = []


def _own_exe():
    if not _own:
        try:
            _own.append(same_exe(psutil.Process().exe()))  # the real one (a venv's python.exe is a launcher)
        except psutil.Error:
            _own.append(same_exe(sys.executable))
    return _own[0]


def _system_program(exe):
    """Programs that ship with Windows, and SpareScreen itself: no point offering them as games."""
    if same_exe(exe) == _own_exe() or _file_name(exe).startswith("sparescreen"):
        return True
    windir = os.environ.get("WINDIR")
    return bool(windir) and same_exe(exe).startswith(same_exe(windir) + os.sep)


def foreground_pid():
    """PID of the focused window, or None where the OS doesn't tell (see the module docstring)."""
    try:
        if sys.platform == "win32":
            return _windows_foreground_pid()
        if sys.platform == "darwin":
            return _mac_foreground_pid()
        if os.environ.get("WAYLAND_DISPLAY"):
            # Don't fall back to xprop here: XWayland only knows about X apps, so it would lie.
            return _wayland_foreground_pid()
        if os.environ.get("DISPLAY"):
            return _x11_foreground_pid()
    except (OSError, AttributeError, ValueError):
        pass
    return None


def same_exe(path):
    """Paths compared the way the OS does (case-insensitive on Windows)."""
    path = os.path.normpath(path or "")
    return path.lower() if sys.platform == "win32" else path


class ActivitySource:
    """Open game, focused program and top processes (summed per program).

    A game is, in this order: never anything the user marked "not a game"; anything in
    the user's "my games"; anything running from a store's library folder (GAME_DIRS);
    or, where FPS is set up (Windows), the full-screen app in front if PresentMon sees
    it drawing like a game (`auto`, see fps.AutoDetect).
    """

    name = "activity"
    IGNORE = {"system idle process", "idle", "system", "registry", "memory compression"}
    SOURCES = {"mine": 2, "library": 1}  # which wins when several programs qualify

    def __init__(self, refresh=3, top=6, config=None, auto=None):
        self.refresh = refresh
        self.top = top
        self.config = config  # ConfigStore with the user's game lists
        self.auto = auto
        self.cores = psutil.cpu_count() or 1
        self.art = GameArt()
        self.running = []  # programs the PC window can mark as games: [{"exe", "name"}]
        self.game_exe = None  # the current game's exe, for "not a game" (kept out of the stream)
        self._at = 0
        self._cache = {"game": None, "focus": None, "top": []}

    def read(self):
        if time.time() - self._at < self.refresh:
            return self._cache
        self._at = time.time()

        lists = self.config.games() if self.config else {"my_games": [], "not_games": []}
        mine = {same_exe(g["exe"]): g["name"] for g in lists["my_games"]}
        not_games = {same_exe(path) for path in lists["not_games"]}
        focus_pid = foreground_pid()
        programs = {}  # exe (or name) -> totals
        game = None
        focus = None
        for proc in psutil.process_iter(["name", "exe", "memory_info", "create_time"]):
            info = proc.info
            name = info["name"] or ""
            if name.lower() in self.IGNORE or proc.pid == 0:
                continue
            try:
                cpu = proc.cpu_percent(None) / self.cores  # the first reading of each process returns 0
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            mem = info["memory_info"].rss if info["memory_info"] else 0
            exe = info["exe"]
            key = exe or name
            prog = programs.setdefault(key, {"name": name, "exe": exe, "cpu": 0.0, "mem": 0, "since": None})
            prog["cpu"] += cpu
            prog["mem"] += mem
            if info["create_time"] and (prog["since"] is None or info["create_time"] < prog["since"]):
                prog["since"] = info["create_time"]

            if proc.pid == focus_pid:
                focus = key
            exe_id = same_exe(exe) if exe else None
            if exe_id in not_games:
                continue
            if exe_id in mine:
                title, source = mine[exe_id] or friendly_name(name, exe), "mine"
            else:
                title, source = game_name(exe), "library"
                if not title or HELPERS.search(name):
                    continue
            rank = (self.SOURCES[source], mem)
            if game is None or rank > game["_rank"]:
                game = {"name": title, "source": source, "_rank": rank, "_key": key, "pid": proc.pid}  # pid: FPS

        if game is None and self.auto and focus in programs:
            game = self._auto_game(focus_pid, programs[focus], not_games, focus)

        self.game_exe = programs[game["_key"]]["exe"] if game else None
        if game:
            prog = programs[game.pop("_key")]
            game.pop("_rank", None)
            game.update(cpu=round(prog["cpu"], 1), mem=prog["mem"], since=prog["since"])
            # "art" and "icon" URLs; Steam art is found by the game's folder name
            game.update(self.art.for_game(prog["exe"], game_name(prog["exe"]) or game["name"]))

        def describe(prog):
            return {
                "name": friendly_name(prog["name"], prog["exe"]),
                "cpu": round(prog["cpu"], 1),
                "mem": prog["mem"],
            }

        heavy = sorted(programs.values(), key=lambda p: (p["cpu"], p["mem"]), reverse=True)
        self._cache = {
            "game": game,
            "focus": describe(programs[focus]) if focus in programs else None,
            "top": [describe(p) for p in heavy[:self.top]],
        }
        # For the PC window's "It's a game": the app in front first, then the busiest ones.
        # Kept out of the data stream (paths include the user name).
        candidates = ([programs[focus]] if focus in programs else []) + heavy
        window = foreground_window() if focus in programs else None
        self.running = []
        for prog in candidates:
            if prog["exe"] and not _system_program(prog["exe"]) and \
                    all(r["exe"] != prog["exe"] for r in self.running):
                name = friendly_name(prog["name"], prog["exe"])
                if prog is programs.get(focus) and window and window["title"]:
                    name = window["title"]  # e.g. "Minecraft 1.21" instead of "Java(TM) Platform SE binary"
                self.running.append({"exe": prog["exe"], "name": name[:60]})
            if len(self.running) >= 8:
                break
        return self._cache

    def _auto_game(self, pid, prog, not_games, key):
        """The full-screen app in front, if PresentMon says it draws like a game."""
        exe = prog["exe"]
        if not exe or same_exe(exe) in not_games or _never_auto(exe):
            return None
        window = foreground_window()
        if not window or not window["fullscreen"] or not self.auto.is_game(pid, exe):
            return None
        name = window["title"] or friendly_name(prog["name"], exe)
        return {"name": name[:60], "source": "auto", "_key": key, "pid": pid}
