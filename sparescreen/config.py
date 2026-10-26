"""Page preferences, saved on the PC in ~/.sparescreen/config.json.

The settings screen on the phone sends changes via POST /config; the agent
validates, saves and sends the config back along with the data (`config` field).
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from .shapes import Json

THEMES = ("graphite", "oled", "terracotta", "neon", "terminal", "light")
SCREENS = ("hardware", "ai", "pc", "music", "photos")  # the game screen only shows in game mode
ROTATE = (0, 10, 20, 30, 60)  # seconds; 0 = does not switch by itself
NIGHT_MODES = ("off", "dim", "clock")  # what the screen shows during night hours
NIGHT_HOURS = ("22-7", "23-7", "0-8")  # "start-end", in the phone's local time
USB_SCREEN = ("keep", "dim", "off")  # what to do with a USB phone's screen (see screen.py)
PHOTO_SECONDS = (5, 10, 20, 30, 60)  # how long each photo stays on the Photos screen
BANNER_MAX = 200  # characters of the scrolling message

DEFAULTS: Json = {
    "theme": "graphite",
    "screens": list(SCREENS),
    "rotate": 20,
    "notify": True,
    "sound": True,
    "fan_names": {},  # original name -> user-given name (e.g. "Fan 2" -> "Radiator")
    "cpu_fan": None,  # which fan shows on the CPU card (user's choice; none by default)
    "claude_limits": False,  # headless check of Claude Code limits (spends a tiny bit of quota)
    "burn_in": True,  # shift the content a few pixels every minute (protects OLED screens)
    "game_mode": True,  # while a game runs, show only the game screen
    "heat_alerts": True,  # alert when the CPU, GPU or a drive stays near its limit
    "usb_screen": "keep",  # phone on USB while the PC is locked or at night: keep, dim or off
    "night_mode": "off",
    "night_hours": "23-7",
    "update_check": True,  # ask GitHub now and then for a newer release (see update.py)
    "photo_seconds": 10,
    "banner": "",  # the scrolling message at the bottom; written in the PC window only
}

CONFIG_FILE = Path.home() / ".sparescreen" / "config.json"
MAX_GAMES = 100


def clean_games(saved: object) -> Json:
    """The user's own game lists, kept on the PC only (they hold paths with the user name):
    "my_games" [{"exe", "name"}] counts as games, "not_games" [exe] never does."""
    def exe(value: object) -> str | None:
        return value.strip()[:400] if isinstance(value, str) and value.strip() else None

    mine: list[Json] = []
    for game in (saved.get("my_games") if isinstance(saved, dict) else None) or []:
        if isinstance(game, dict) and exe(game.get("exe")):
            name = game["name"] if isinstance(game.get("name"), str) else ""
            mine.append({"exe": exe(game["exe"]), "name": name.strip()[:60]})
    others = [exe(path) for path in (saved.get("not_games") if isinstance(saved, dict) else None) or []]
    return {"my_games": mine[:MAX_GAMES], "not_games": [p for p in others if p][:MAX_GAMES]}


def clean(data: object) -> Json:
    """Keeps only valid keys and values; the rest is ignored."""
    if not isinstance(data, dict):
        return {}
    out: Json = {}
    if data.get("theme") in THEMES:
        out["theme"] = data["theme"]
    if isinstance(data.get("screens"), list):
        wanted = ["ai" if s == "claude" else s for s in data["screens"]]  # "claude" was renamed to "ai"
        screens = [s for s in SCREENS if s in wanted]
        if screens:  # at least one screen
            out["screens"] = screens
    if data.get("rotate") in ROTATE:
        out["rotate"] = data["rotate"]
    for key in ("notify", "sound", "claude_limits", "burn_in", "game_mode", "heat_alerts",
                "update_check"):
        if isinstance(data.get(key), bool):
            out[key] = data[key]
    if data.get("night_mode") in NIGHT_MODES:
        out["night_mode"] = data["night_mode"]
    if data.get("usb_screen") in USB_SCREEN:
        out["usb_screen"] = data["usb_screen"]
    if data.get("photo_seconds") in PHOTO_SECONDS:
        out["photo_seconds"] = data["photo_seconds"]
    if data.get("night_hours") in NIGHT_HOURS:
        out["night_hours"] = data["night_hours"]
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

    def __init__(self, path: Path = CONFIG_FILE) -> None:
        self.path = path
        self._lock = threading.Lock()
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = {}
        self._config = {**DEFAULTS, **clean(saved)}
        self._games = clean_games(saved)
        # The photo folder stays on the PC (a path, with the user name in it): it's not part
        # of the config the page gets, and only the PC window changes it, like the banner.
        folder = saved.get("photos_dir") if isinstance(saved, dict) else None
        self._photos_dir: str | None = folder if isinstance(folder, str) and folder else None
        banner = saved.get("banner") if isinstance(saved, dict) else None
        if isinstance(banner, str):
            self._config["banner"] = banner[:BANNER_MAX]
        # Screens added in a newer version start on: anything the saved file has never
        # seen joins the list (files from before this existed knew the first three).
        known = saved.get("screens_known") if isinstance(saved, dict) else None
        if not isinstance(known, list):
            known = ["hardware", "ai", "claude", "pc"]
        self._config["screens"] = [s for s in SCREENS if s in self._config["screens"] or s not in known]

    def read(self) -> Json:
        with self._lock:
            return dict(self._config)

    def games(self) -> Json:
        with self._lock:
            return {"my_games": [dict(g) for g in self._games["my_games"]],
                    "not_games": list(self._games["not_games"])}

    def set_games(self, my_games: list[Json] | None = None, not_games: list[str] | None = None) -> None:
        """Changed from the PC window only (POST /config ignores these lists)."""
        with self._lock:
            self._games = clean_games({"my_games": self._games["my_games"] if my_games is None else my_games,
                                       "not_games": self._games["not_games"] if not_games is None else not_games})
        self.update({})

    def photos_dir(self) -> str | None:
        with self._lock:
            return self._photos_dir

    def set_photos_dir(self, folder: str | None) -> None:
        """From the PC window only (POST /config ignores it)."""
        with self._lock:
            self._photos_dir = folder or None
        self.update({})

    def set_banner(self, text: str) -> None:
        """From the PC window only (POST /config ignores it)."""
        with self._lock:
            self._config["banner"] = " ".join(text.split())[:BANNER_MAX]
        self.update({})

    def update(self, changes: object) -> Json:
        with self._lock:
            self._config.update(clean(changes))
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            saved = dict(self._config, screens_known=list(SCREENS), photos_dir=self._photos_dir, **self._games)
            tmp.write_text(json.dumps(saved, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
            return dict(self._config)
