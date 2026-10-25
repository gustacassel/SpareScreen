"""When to rest the phone's screen (over USB): while the PC is locked, or at night.

Night mode on the page only covers the dashboard with a dark layer; the backlight stays
on. Over USB the agent can do better: turn the real brightness all the way down, or turn
the screen off, and put things back afterwards (usb.py applies it). That spares the
phone's battery some heat and an OLED screen some burn-in.

The user picks it in the settings ("Phone screen (USB)": keep, dim or off). It applies
while this PC is locked, and during the night hours when night mode is on.
"""

from __future__ import annotations

import datetime
import os
import shutil
import subprocess
import sys
from typing import TYPE_CHECKING, Any, Optional

import psutil

if TYPE_CHECKING:
    from .config import ConfigStore

ACTIONS = ("keep", "dim", "off")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def in_night_hours(hours: Any, now: Optional[datetime.datetime] = None) -> bool:
    """'23-7' -> True from 23:00 to 06:59 (the same rule the page uses)."""
    try:
        start, end = (int(part) for part in hours.split("-"))
    except (AttributeError, ValueError):
        return False
    hour = (now or datetime.datetime.now()).hour
    return start <= hour < end if start < end else hour >= start or hour < end


def pc_locked() -> bool:
    """True while this PC shows its lock screen; False if unknown (other systems)."""
    try:
        if sys.platform == "win32":
            # The lock screen (and the sign-in screen) is drawn by LogonUI.exe.
            return any((p.info["name"] or "").lower() == "logonui.exe" for p in psutil.process_iter(["name"]))
        if sys.platform.startswith("linux") and shutil.which("loginctl") and os.environ.get("XDG_SESSION_ID"):
            result = subprocess.run(["loginctl", "show-session", os.environ["XDG_SESSION_ID"], "-p", "LockedHint"],
                                    capture_output=True, text=True, timeout=2)
            return result.stdout.strip() == "LockedHint=yes"
    except (OSError, subprocess.SubprocessError, psutil.Error):
        pass
    return False


def wanted(config: ConfigStore, now: Optional[datetime.datetime] = None,
           locked: Optional[bool] = None) -> Optional[str]:
    """"dim", "off" or None (leave the screen as the user has it)."""
    settings = config.read()
    action: str = settings.get("usb_screen", "keep")
    if action not in ("dim", "off"):
        return None
    night = settings.get("night_mode", "off") != "off" and in_night_hours(settings.get("night_hours"), now)
    if night or (pc_locked() if locked is None else locked):
        return action
    return None
