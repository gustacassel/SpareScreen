"""Demo mode (sparescreen --demo): made-up but realistic data.

Useful for screenshots (no personal session or app names), for trying the
interface on a machine without sensors, and for working on the page. The data
has exactly the same shape as the real sources, and drifts slowly so the
screens look alive.
"""

from __future__ import annotations

import math
import time
from typing import Optional

from .shapes import Json, Source

GB = 1024 ** 3


def _wave(period: float, low: float, high: float, phase: float = 0.0) -> float:
    """A value that drifts smoothly between low and high."""
    t = time.time() / period * 2 * math.pi + phase
    return low + (high - low) * (math.sin(t) + 1) / 2


class DemoSystem:
    name = "system"

    def __init__(self) -> None:
        self.started = time.time()

    def read(self) -> Json:
        # Slow swings plus a quicker wobble per core: lively numbers, and charts of the
        # last minutes that look like a PC at work rather than a zigzag.
        load = _wave(110, 15, 55)
        cores = [round(min(100, max(1, load + _wave(7 + i, -12, 12, i))), 1) for i in range(12)]
        cpu = round(sum(cores) / len(cores), 1)
        gpu = round(_wave(95, 30, 90) + _wave(11, -4, 4), 1)
        ram_used = _wave(60, 14, 19) * GB
        return {
            "cpu": {
                "name": "Ryzen 7 7700X",
                "percent": cpu,
                "cores": cores,
                "temp": round(45 + cpu * 0.35, 1),
                "power": round(30 + cpu * 0.9, 1),
                "clock": 4300 + cpu * 9,
                "clock_max": 5400,
                "temp_limit": 95,
            },
            "gpu": {
                "name": "RTX 4070",
                "percent": gpu,
                "temp": round(40 + gpu * 0.3, 1),
                "temp_limit": 88,
                "mem_used": _wave(40, 5, 9) * GB,
                "mem_total": 12 * GB,
                "power": round(25 + gpu * 1.6, 1),
                "fan": round(max(0, gpu - 40) * 0.9, 1),
                "clock": round(1200 + gpu * 14),
                "mem_clock": 10501,
            },
            "ram": {
                "name": "32 GB DDR5-6000",
                "percent": round(100 * ram_used / (32 * GB), 1),
                "used": ram_used,
                "total": 32 * GB,
                "available": 32 * GB - ram_used,
                "swap_percent": 4.0,
                "swap_total": 8 * GB,
                "processes": 287,
            },
            "fans": [
                {"name": "Fan 1", "rpm": round(_wave(30, 900, 1500)), "percent": None, "gpu": False},
                {"name": "Fan 2", "rpm": round(_wave(30, 2400, 2700, 1)), "percent": None, "gpu": False},
                {"name": "Fan 3", "rpm": 820, "percent": None, "gpu": False},
                {"name": "Fan 4", "rpm": 790, "percent": None, "gpu": False},
                {"name": "GPU", "rpm": round(max(0, gpu - 40) * 30), "percent": round(max(0, gpu - 40) * 0.9, 1),
                 "gpu": True},
            ],
            "drives": [
                {"name": "NVMe SSD 2TB", "temp": 41.0, "temp_limit": 75.0, "read": 0.0, "write": 2.1e6},
                {"name": "SATA SSD 1TB", "temp": 34.0, "temp_limit": None, "read": 0.0, "write": 0.0},
            ],
            "net": {"down": _wave(70, 2e5, 8.4e6), "up": _wave(110, 3e4, 9e5)},
            "disks": [
                {"name": "C:", "percent": 62.0, "free": 380 * GB, "total": 1000 * GB},
                {"name": "D:", "percent": 41.0, "free": 1180 * GB, "total": 2000 * GB},
            ],
            "uptime": 3 * 3600 + 27 * 60 + (time.time() - self.started),
            "sensors_hint": None,
        }


def _window(label: str, percent: float, resets_in: float, weekly: bool) -> Json:
    return {"label": label, "percent": percent, "resets_at": time.time() + resets_in,
            "renewed": False, "weekly": weekly}


class DemoClaude:
    name = "claude"
    CYCLE = 90  # every 90 s one session goes busy -> idle, showing the "finished" alert

    def read(self) -> Json:
        now = time.time()
        busy = (now % self.CYCLE) < self.CYCLE * 0.6
        hour = 3600
        return {
            "installed": True,
            "name": "Claude Code",
            "limits": [
                _window("5 hours", round(_wave(300, 30, 45), 1), 2 * hour + 13 * 60, False),
                _window("Week", 58.0, 3 * 24 * hour + 9 * hour, True),
            ],
            "limits_updated": now - 40,
            "limits_hint": None,
            "today": {"input": 2.1e6, "output": 4.6e5, "cache_read": 3.84e7, "responses": 412,
                      "models": {"claude-opus-demo": 300, "claude-sonnet-demo": 112}},
            "week_models": [{"model": "claude-opus-demo", "label": "Opus", "tokens": 1.42e8},
                            {"model": "claude-sonnet-demo", "label": "Sonnet", "tokens": 3.1e7}],
            "sessions": [
                {"id": "demo-1", "name": "Fix flaky integration tests", "project": "backend",
                 "status": "busy" if busy else "idle", "since": now - (now % self.CYCLE if busy else 5)},
                {"id": "demo-2", "name": "Add dark mode to settings page", "project": "webapp",
                 "status": "busy", "since": now - 160},
                {"id": "demo-3", "name": "Write release notes", "project": "docs",
                 "status": "idle", "since": now - 25 * 60},
            ],
        }


class DemoCodex:
    name = "codex"

    def read(self) -> Json:
        now = time.time()
        hour = 3600
        return {
            "installed": True,
            "name": "Codex",
            "limits": [
                _window("5 hours", round(_wave(400, 10, 20), 1), 4 * hour + 2 * 60, False),
                _window("Week", 22.0, 5 * 24 * hour + 2 * hour, True),
            ],
            "limits_updated": now - 300,
            "limits_hint": None,
            "today": {"input": 6.2e5, "output": 1.1e5, "cache_read": 4.4e6, "responses": 58,
                      "models": {"gpt-codex-demo": 58}},
            "week_models": [{"model": "gpt-codex-demo", "label": "gpt-codex", "tokens": 2.3e7}],
            "sessions": [
                {"id": "codex:demo-1", "name": "Port CSV export to the new API", "project": "reports",
                 "status": "idle", "since": now - 12 * 60},
                {"id": "codex:demo-2", "name": "Review database migrations", "project": "backend",
                 "status": "idle", "since": now - 3 * hour},
            ],
        }


class DemoGemini:
    name = "gemini"

    def read(self) -> Json:
        now = time.time()
        return {
            "installed": True,
            "name": "Gemini CLI",
            "limits": [],
            "limits_updated": None,
            "limits_hint": "Gemini CLI doesn't save its limits on this PC.",
            "today": {"input": 3.1e5, "output": 6.4e4, "cache_read": 1.2e6, "responses": 31,
                      "models": {"gemini-demo-pro": 31}},
            "week_models": [{"model": "gemini-demo-pro", "label": "Gemini Demo Pro", "tokens": 9.8e6}],
            "sessions": [
                {"id": "gemini:demo-1", "name": "Write tests for the date parser", "project": "parser-lib",
                 "status": "idle", "since": now - 40 * 60},
            ],
        }


class DemoActivity:
    name = "activity"
    # The game "runs" one minute out of every four, so the demo also shows game mode
    # without hiding the other screens for good.
    CYCLE, PLAYING = 240, 60

    def __init__(self) -> None:
        self.started = time.time() - (47 * 60)
        self.running: list[Json] = []  # the PC window's "It's a game" list: nothing to offer in the demo
        self.game_exe: Optional[str] = None

    def refresh_soon(self) -> None:
        pass  # made-up data: nothing to look up again

    def read(self) -> Json:
        playing = time.time() % self.CYCLE < self.PLAYING
        game: Json = {"name": "Hollow Peaks", "cpu": round(_wave(11, 18, 32), 1), "mem": 6.4 * GB}
        apps: list[Json] = [
            {"name": "Google Chrome", "cpu": 3.1, "mem": 2.3 * GB},
            {"name": "Visual Studio Code", "cpu": round(_wave(17, 1, 6), 1), "mem": 1.1 * GB},
            {"name": "Spotify", "cpu": 1.4, "mem": 0.4 * GB},
            {"name": "Discord", "cpu": 1.2, "mem": 0.6 * GB},
            {"name": "Windows Explorer", "cpu": 0.6, "mem": 0.2 * GB},
            {"name": "Steam", "cpu": 0.4, "mem": 0.3 * GB},
        ]
        if not playing:
            return {"game": None, "focus": apps[1], "top": sorted(apps, key=lambda a: -a["cpu"])}
        return {
            "game": dict(game, since=self.started, art="demo-game.svg", icon="demo-game-icon.svg", pid=4242),
            "focus": game,
            "top": [game] + apps[:5],
        }


class DemoPhone:
    name = "phone"

    def read(self) -> Json:
        return {"devices": [{"model": "Demo phone", "level": 87, "temp": round(_wave(120, 31, 36), 1),
                             "status": "charging", "health": "good", "plugged": True}]}


class DemoMedia:
    name = "media"
    DURATION = 228.0  # the song loops, so the progress bar keeps moving

    def read(self) -> Json:
        return {"available": True, "playing": True, "title": "Midnight Drive", "artist": "Neon Arcade",
                "album": "Night Shift", "app": "Spotify", "status": "playing",
                "position": round(time.time() % self.DURATION, 1), "duration": self.DURATION,
                "art": "demo-cover.svg", "app_icon": None}


class DemoFps:
    name = "fps"

    def __init__(self, activity: DemoActivity) -> None:
        self.activity = activity

    def read(self) -> Json:
        if not self.activity.read()["game"]:
            return {"available": True, "playing": False}
        fps = round(_wave(9, 128, 152))
        return {"available": True, "playing": True, "error": None, "fps": fps,
                "low1": round(fps * 0.72), "frametime": round(1000 / fps, 1)}


def demo_sources() -> list[Source]:
    activity = DemoActivity()
    return [DemoSystem(), DemoClaude(), DemoCodex(), DemoGemini(), activity, DemoFps(activity), DemoPhone(), DemoMedia()]
