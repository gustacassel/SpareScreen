"""What is running on the PC: open game, focused program and the heaviest processes.

Which program is the game is decided in games.py; this module walks the processes and
asks the OS what's in front: user32 on Windows; on Linux xdotool/xprop (X11) or
swaymsg/hyprctl (Sway/Hyprland, the Wayland desktops that allow it); `lsappinfo` on
macOS. Anything else just shows no focused program.
"""

from __future__ import annotations

import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import time
from typing import TYPE_CHECKING, Any, cast

import psutil

from .games import GameFinder, system_program
from .shapes import Json

if TYPE_CHECKING:
    from .config import ConfigStore
    from .fps import AutoDetect


# ---- Friendly program name (Windows: the .exe "File description") -----------

_descriptions: dict[str, str] = {}


def _file_description(exe: str) -> str | None:
    """'C:/.../chrome.exe' -> 'Google Chrome', read from the executable's version resource."""
    if sys.platform != "win32":
        return None
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
    if not version.VerQueryValueW(buf, key, ctypes.byref(ptr), ctypes.byref(length)) or not length.value \
            or not ptr.value:
        return None
    # Some files report a length past the end of the text: stop at the first null.
    return ctypes.wstring_at(ptr.value, length.value).split("\x00", 1)[0].strip() or None


def friendly_name(name: str, exe: str | None) -> str:
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

def _run(args: list[str]) -> str | None:
    """stdout of a quick helper command, or None if it is missing, slow or fails."""
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=1)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return result.stdout if result.returncode == 0 else None


def _pid(value: Any) -> int | None:
    """A real PID or None (helpers report 0 or -1 when nothing has focus)."""
    try:
        pid = int(value)
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


def _windows_foreground_pid() -> int | None:
    if sys.platform != "win32":
        return None
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value or None


def _x11_foreground_pid() -> int | None:
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


def _sway_focused(node: Json) -> int | None:
    """Focused window in `swaymsg -t get_tree`, searching tiled and floating windows."""
    if node.get("focused") and _pid(node.get("pid")):
        return _pid(node["pid"])
    for child in (node.get("nodes") or []) + (node.get("floating_nodes") or []):
        pid = _sway_focused(child)
        if pid:
            return pid
    return None


def _wayland_foreground_pid() -> int | None:
    """Wayland hides other apps' windows on purpose; only some compositors tell us via their CLI."""
    try:
        if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") and shutil.which("hyprctl"):
            data = json.loads(_run([cast(str, shutil.which("hyprctl")), "activewindow", "-j"]) or "{}")
            return _pid(data.get("pid"))
        if os.environ.get("SWAYSOCK") and shutil.which("swaymsg"):
            return _sway_focused(json.loads(_run([cast(str, shutil.which("swaymsg")), "-t", "get_tree"]) or "{}"))
    except (ValueError, TypeError, AttributeError):
        pass
    return None


def _mac_foreground_pid() -> int | None:
    # lsappinfo ships with macOS and, unlike AppleScript/System Events, needs no Automation permission.
    lsappinfo = shutil.which("lsappinfo")
    if not lsappinfo:
        return None
    front = (_run([lsappinfo, "front"]) or "").strip()  # 'ASN:0x0-0x1d01d:'
    if not front.startswith("ASN:"):
        return None
    match = re.search(r'"pid"\s*=\s*(\d+)', _run([lsappinfo, "info", "-only", "pid", front]) or "")
    return _pid(match.group(1)) if match else None


def _windows_foreground_window() -> Json | None:
    if sys.platform != "win32":
        return None
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
    return {"title": title.value.strip(), "fullscreen": fullscreen, "hwnd": hwnd}


def foreground_window() -> Json | None:
    """{"title", "fullscreen"} of the window in front (Windows), else None."""
    if sys.platform != "win32":
        return None
    try:
        return _windows_foreground_window()
    except (OSError, AttributeError, ValueError):
        return None


def foreground_pid() -> int | None:
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
    """Open game (see games.py), focused program and top processes (summed per program)."""

    name = "activity"
    IGNORE = {"system idle process", "idle", "system", "registry", "memory compression"}

    def __init__(self, refresh: float = 3, top: int = 6, config: ConfigStore | None = None,
                 auto: AutoDetect | None = None) -> None:
        self.refresh = refresh
        self.top = top
        self.games = GameFinder(config, auto)
        self.cores = psutil.cpu_count() or 1
        self.running: list[dict[str, str]] = []  # programs the PC window can mark as games: [{"exe", "name"}]
        self._at: float = 0
        self._cache: Json = {"game": None, "focus": None, "top": []}

    def refresh_soon(self) -> None:
        self._at = 0

    @property
    def game_exe(self) -> str | None:
        """The current game's exe, for "not a game" (kept out of the data stream)."""
        return self.games.exe

    def read(self) -> Json:
        if time.time() - self._at < self.refresh:
            return self._cache
        self._at = time.time()

        focus_pid = foreground_pid()
        programs: dict[str, Json] = {}  # exe (or name) -> totals
        focus: str | None = None
        self.games.begin()
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
            self.games.consider(proc.pid, name, exe, mem, key, friendly_name)

        window = foreground_window() if focus in programs else None
        game = self.games.finish(programs, focus, focus_pid, window, friendly_name)

        def describe(prog: Json) -> Json:
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
        self.running = []
        for prog in candidates:
            if prog["exe"] and not system_program(prog["exe"]) and \
                    all(r["exe"] != prog["exe"] for r in self.running):
                name = friendly_name(prog["name"], prog["exe"])
                if focus is not None and prog is programs.get(focus) and window and window["title"]:
                    name = window["title"]  # e.g. "Minecraft 1.21" instead of "Java(TM) Platform SE binary"
                self.running.append({"exe": prog["exe"], "name": name[:60]})
            if len(self.running) >= 8:
                break
        return self._cache
