"""Page preferences, saved on the PC in ~/.sparescreen/config.json.

The settings screen on the phone sends changes via POST /config; the agent
validates, saves and sends the config back along with the data (`config` field).
"""

import json
import os
import threading
from pathlib import Path

THEMES = ("graphite", "oled", "terracotta", "neon", "terminal", "light")
SCREENS = ("hardware", "ai", "pc")
ROTATE = (0, 10, 20, 30, 60)  # seconds; 0 = does not switch by itself

DEFAULTS = {
    "theme": "graphite",
    "screens": list(SCREENS),
    "rotate": 20,
    "notify": True,
    "sound": True,
    "fan_names": {},  # original name -> user-given name (e.g. "Fan 2" -> "Radiator")
    "cpu_fan": None,  # which fan shows on the CPU card (user's choice; none by default)
}

CONFIG_FILE = Path.home() / ".sparescreen" / "config.json"


def clean(data):
    """Keeps only valid keys and values; the rest is ignored."""
    if not isinstance(data, dict):
        return {}
    out = {}
    if data.get("theme") in THEMES:
        out["theme"] = data["theme"]
    if isinstance(data.get("screens"), list):
        wanted = ["ai" if s == "claude" else s for s in data["screens"]]  # "claude" was renamed to "ai"
        screens = [s for s in SCREENS if s in wanted]
        if screens:  # at least one screen
            out["screens"] = screens
    if data.get("rotate") in ROTATE:
        out["rotate"] = data["rotate"]
    for key in ("notify", "sound"):
        if isinstance(data.get(key), bool):
            out[key] = data[key]
    if "cpu_fan" in data and (data["cpu_fan"] is None or isinstance(data["cpu_fan"], str)):
        out["cpu_fan"] = data["cpu_fan"][:20] if data["cpu_fan"] else None
    names = data.get("fan_names")
    if isinstance(names, dict):  # empty name = back to the original name
        out["fan_names"] = {
            str(fan)[:20]: name.strip()[:16]
            for fan, name in names.items()
            if isinstance(name, str) and name.strip()
        }
    return out


class ConfigStore:
    """Also works as a data source: the page gets the config on every reading."""

    name = "config"

    def __init__(self, path=CONFIG_FILE):
        self.path = path
        self._lock = threading.Lock()
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = {}
        self._config = {**DEFAULTS, **clean(saved)}

    def read(self):
        with self._lock:
            return dict(self._config)

    def update(self, changes):
        with self._lock:
            self._config.update(clean(changes))
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._config, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
            return dict(self._config)
