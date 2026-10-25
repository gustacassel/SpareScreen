"""Demo mode (sparescreen --demo): made-up but realistic data.

Useful for screenshots (no personal session or app names), for trying the
interface on a machine without sensors, and for working on the page. The data
has exactly the same shape as the real sources, and drifts slowly so the
screens look alive.
"""

import math
import time

GB = 1024 ** 3


def _wave(period, low, high, phase=0.0):
    """A value that drifts smoothly between low and high."""
    t = time.time() / period * 2 * math.pi + phase
    return low + (high - low) * (math.sin(t) + 1) / 2


class DemoSystem:
    name = "system"

    def __init__(self):
        self.started = time.time()

    def read(self):
        cores = [round(_wave(7 + i, 5, 70, i), 1) for i in range(12)]
        cpu = round(sum(cores) / len(cores), 1)
        gpu = round(_wave(23, 30, 95), 1)
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
            },
            "gpu": {
                "name": "RTX 4070",
                "percent": gpu,
                "temp": round(40 + gpu * 0.3, 1),
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
                {"name": "NVMe SSD 2TB", "temp": 41.0, "read": 0.0, "write": 2.1e6},
                {"name": "SATA SSD 1TB", "temp": 34.0, "read": 0.0, "write": 0.0},
            ],
            "net": {"down": _wave(9, 2e5, 8.4e6), "up": _wave(13, 3e4, 9e5)},
            "disks": [
                {"name": "C:", "percent": 62.0, "free": 380 * GB, "total": 1000 * GB},
                {"name": "D:", "percent": 41.0, "free": 1180 * GB, "total": 2000 * GB},
            ],
            "uptime": 3 * 3600 + 27 * 60 + (time.time() - self.started),
        }


def _window(label, percent, resets_in, weekly):
    return {"label": label, "percent": percent, "resets_at": time.time() + resets_in,
            "renewed": False, "weekly": weekly}


class DemoClaude:
    name = "claude"
    CYCLE = 90  # every 90 s one session goes busy -> idle, showing the "finished" alert

    def read(self):
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

    def read(self):
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


class DemoActivity:
    name = "activity"

    def __init__(self):
        self.started = time.time() - (47 * 60)

    def read(self):
        return {
            "game": {"name": "Hollow Peaks", "cpu": round(_wave(11, 18, 32), 1), "mem": 6.4 * GB, "since": self.started},
            "focus": {"name": "Hollow Peaks", "cpu": round(_wave(11, 18, 32), 1), "mem": 6.4 * GB},
            "top": [
                {"name": "Hollow Peaks", "cpu": round(_wave(11, 18, 32), 1), "mem": 6.4 * GB},
                {"name": "Google Chrome", "cpu": 3.1, "mem": 2.3 * GB},
                {"name": "Discord", "cpu": 1.2, "mem": 0.6 * GB},
                {"name": "Visual Studio Code", "cpu": 0.8, "mem": 1.1 * GB},
            ],
        }


class DemoPhone:
    name = "phone"

    def read(self):
        return {"devices": [{"model": "Demo phone", "level": 87, "temp": round(_wave(120, 31, 36), 1),
                             "status": "charging", "health": "good", "plugged": True}]}


def demo_sources():
    return [DemoSystem(), DemoClaude(), DemoCodex(), DemoActivity(), DemoPhone()]
