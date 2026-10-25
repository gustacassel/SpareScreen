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
    return ctypes.wstring_at(ptr.value, length.value).rstrip("\x00").strip() or None


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


class ActivitySource:
    """Open game, focused program and top processes (summed per program)."""

    name = "activity"
    IGNORE = {"system idle process", "idle", "system", "registry", "memory compression"}

    def __init__(self, refresh=3, top=4):
        self.refresh = refresh
        self.top = top
        self.cores = psutil.cpu_count() or 1
        self._at = 0
        self._cache = {"game": None, "focus": None, "top": []}

    def read(self):
        if time.time() - self._at < self.refresh:
            return self._cache
        self._at = time.time()

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

            title = game_name(exe)
            if title and not HELPERS.search(name):
                if game is None or mem > game["_mem"]:
                    game = {"name": title, "_mem": mem, "_key": key}
            if proc.pid == focus_pid:
                focus = key

        if game:
            prog = programs[game.pop("_key")]
            game.pop("_mem")
            game.update(cpu=round(prog["cpu"], 1), mem=prog["mem"], since=prog["since"])

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
        return self._cache
