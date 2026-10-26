"""Data sources shown on the dashboard."""

from __future__ import annotations

import sys
import time
from typing import TYPE_CHECKING, Optional

import psutil

from .hwinfo import cpu_name, ram_name
from .sensors import Sensors, cpu_limit
from .shapes import Json, Source

if TYPE_CHECKING:
    from .config import ConfigStore


class SystemSource:
    """CPU, GPU and RAM usage and temperature, fans, disks and network."""

    name = "system"

    def __init__(self) -> None:
        # psutil's first reading always returns 0%; throw it away.
        psutil.cpu_percent(percpu=True)
        self.sensors = Sensors()
        self.cpu_name = cpu_name()
        self.ram_name = ram_name(psutil.virtual_memory().total)
        self._net = (time.time(), psutil.net_io_counters())
        self._disks_at: float = 0
        self._disks: list[Json] = []

    def read(self) -> Json:
        per_core = psutil.cpu_percent(percpu=True)
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        sensors = self.sensors.read()
        return {
            "cpu": {
                "name": self.cpu_name,
                "percent": round(sum(per_core) / len(per_core), 1),
                "cores": per_core,
                "temp": sensors["cpu_temp"],
                "power": sensors["cpu_power"],
                "clock": sensors["cpu_clock"],
                "clock_max": sensors["cpu_clock_max"],
                # Where it starts to throttle: from the CPU when it says, else by family.
                "temp_limit": sensors["cpu_temp_limit"] or cpu_limit(self.cpu_name),
            },
            "gpu": sensors["gpu"],
            "ram": {
                "name": self.ram_name,
                "percent": mem.percent,
                "used": mem.total - mem.available,
                "total": mem.total,
                "available": mem.available,
                "swap_percent": swap.percent,
                "swap_total": swap.total,
                "processes": len(psutil.pids()),
            },
            "fans": sensors["fans"],
            "drives": sensors["drives"],
            "net": self._net_rates(),
            "disks": self._partitions(),
            "uptime": time.time() - psutil.boot_time(),
            "sensors_hint": sensors.get("hint"),  # what to do when sensors are missing, or None
        }

    def _net_rates(self) -> dict[str, float]:
        now, counters = time.time(), psutil.net_io_counters()
        then, before = self._net
        self._net = (now, counters)
        elapsed = max(now - then, 1e-6)
        return {
            "down": (counters.bytes_recv - before.bytes_recv) / elapsed,
            "up": (counters.bytes_sent - before.bytes_sent) / elapsed,
        }

    def _partitions(self) -> list[Json]:
        """Space on each drive (C:, D:...), read every 30 s."""
        if time.time() - self._disks_at < 30:
            return self._disks
        self._disks_at = time.time()
        disks: list[Json] = []
        for part in psutil.disk_partitions(all=False):
            if "cdrom" in part.opts or part.fstype in ("", "squashfs", "tmpfs"):
                continue
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except OSError:
                continue
            disks.append({
                "name": part.mountpoint.rstrip("\\/") or part.mountpoint,
                "percent": usage.percent,
                "free": usage.free,
                "total": usage.total,
            })
        self._disks = disks
        return disks


def default_sources(config: Optional[ConfigStore] = None) -> list[Source]:
    from .activity import ActivitySource
    from .claude import ClaudeSource
    from .claude_probe import LimitsProbe
    from .codex import CodexSource
    from .fps import AutoDetect, FpsSource
    from .gemini import GeminiSource
    from .media import MediaSource

    claude = ClaudeSource(probe=LimitsProbe(), probe_enabled=lambda: bool(config and config.read()["claude_limits"]))
    activity = ActivitySource(config=config, auto=AutoDetect() if sys.platform == "win32" else None)
    return [SystemSource(), claude, CodexSource(), GeminiSource(), activity, FpsSource(activity), MediaSource()]
