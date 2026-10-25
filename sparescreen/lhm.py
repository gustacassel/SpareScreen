"""LibreHardwareMonitor on Windows: find it, turn on its web server, start it, install it.

CPU temperature, clocks and fans on Windows need a kernel driver, so they come from
LibreHardwareMonitor (free, MPL-2.0), which runs as administrator. SpareScreen reads
its web server (sensors.py). From the PC window it can also:
- turn on the web server (and "start minimized to the tray") in its config file,
  which only works while it's closed, since it saves its settings when it exits;
- start it (Windows asks for admin rights, as it always does for LibreHardwareMonitor);
- install it with winget, in a console window where the user sees what happens.
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterator, Optional, cast

import psutil

EXE = "LibreHardwareMonitor.exe"
WINGET_ID = "LibreHardwareMonitor.LibreHardwareMonitor"
DEFAULT_PORT = 8085
# Web server on (what SpareScreen reads) and out of the way: minimized to the tray.
SETTINGS = {"runWebServerMenuItem": "true", "startMinMenuItem": "true", "minTrayMenuItem": "true"}
CANCELLED = 1223  # Windows error when the user says no to the admin prompt


def candidates() -> Iterator[str]:
    """Where the usual ways of installing it put the executable."""
    env = os.environ.get
    patterns = [
        os.path.join(env("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Packages", WINGET_ID + "_*", EXE),
        os.path.join(env("LOCALAPPDATA", ""), "Programs", "LibreHardwareMonitor", EXE),
        os.path.join(env("ProgramFiles", ""), "LibreHardwareMonitor", EXE),
        os.path.join(env("ProgramFiles(x86)", ""), "LibreHardwareMonitor", EXE),
        os.path.join(os.path.expanduser("~"), "scoop", "apps", "librehardwaremonitor", "current", EXE),
        os.path.join(env("ProgramData", ""), "chocolatey", "lib", "librehardwaremonitor", "tools", EXE),
    ]
    for pattern in patterns:
        yield from sorted(glob.glob(pattern))


def running() -> bool:
    return any((p.info["name"] or "").lower() == EXE.lower() for p in psutil.process_iter(["name"]))


def find() -> Optional[str]:
    """Path of LibreHardwareMonitor.exe, or None if it isn't installed anywhere we know."""
    for proc in psutil.process_iter(["name", "exe"]):
        if (proc.info["name"] or "").lower() == EXE.lower() and proc.info["exe"]:
            return cast(str, proc.info["exe"])  # running from wherever the user unzipped it
    return next(iter(candidates()), None)


def _config_path(exe: str) -> Path:
    return Path(exe).with_name("LibreHardwareMonitor.config")


def read_settings(exe: str) -> dict[str | None, str | None]:
    """Its appSettings as a dict ({} when there's no config yet)."""
    try:
        root = ET.parse(_config_path(exe)).getroot()
    except (OSError, ET.ParseError):
        return {}
    return {node.get("key"): node.get("value") for node in root.iter("add")}


def port(exe: str) -> int:
    """The port its web server uses (the user may have changed it)."""
    try:
        return int(read_settings(exe).get("listenerPort") or DEFAULT_PORT)
    except ValueError:
        return DEFAULT_PORT


def enable_web_server(exe: str) -> bool:
    """Turns on SETTINGS in its config file. False when the file can't be written
    (e.g. installed under Program Files); the user then turns it on in its menu."""
    path = _config_path(exe)
    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except ET.ParseError:
        return False
    except OSError:  # never started yet: start a config of our own
        root = ET.Element("configuration")
        tree = ET.ElementTree(root)
    settings = root.find("appSettings")
    if settings is None:
        settings = ET.SubElement(root, "appSettings")
    nodes = {node.get("key"): node for node in settings.iter("add")}
    for key, value in SETTINGS.items():
        node = nodes.get(key)
        if node is None:
            node = ET.SubElement(settings, "add", key=key)
        node.set("value", value)
    try:
        tree.write(path, encoding="utf-8", xml_declaration=True)
    except OSError:
        return False
    return True


def start(exe: str) -> Optional[str]:
    """Starts it (with the admin prompt Windows shows for it). Returns an error message or None."""
    if sys.platform != "win32":  # os.startfile is Windows only; so is LibreHardwareMonitor
        return "LibreHardwareMonitor only runs on Windows."
    configured = enable_web_server(exe)
    try:
        os.startfile(exe)  # the shell handles the elevation its manifest asks for
    except OSError as exc:
        if getattr(exc, "winerror", None) == CANCELLED:
            return "Windows asked for permission and it was refused."
        return f"Couldn't start it: {exc}"
    if not configured:
        return "Started. Turn on its web server: Options > Remote Web Server > Run."
    return None


def install() -> Optional[str]:
    """Installs it with winget in a visible console. Returns an error message or None."""
    winget = shutil.which("winget")
    if not winget:
        return "winget isn't available: download LibreHardwareMonitor from its GitHub releases page."
    subprocess.Popen([winget, "install", "--id", WINGET_ID, "--exact"],
                     creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
    return None
