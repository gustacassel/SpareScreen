"""Start SpareScreen when you log in (sparescreen --autostart on|off|status).

Each OS has its own per-user mechanism; none of them needs admin rights:
- Windows: a value under HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run.
- Linux: an XDG autostart entry in ~/.config/autostart (most desktops honor it).
- macOS: a LaunchAgent in ~/Library/LaunchAgents (takes effect at the next login).

The agent starts with --background: no window, output goes to a log file.
"""

import os
import plistlib
import shlex
import subprocess
import sys
from pathlib import Path

APP = "SpareScreen"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
DESKTOP_FILE = Path.home() / ".config" / "autostart" / "sparescreen.desktop"
LAUNCH_AGENT = Path.home() / "Library" / "LaunchAgents" / "io.github.gustacassel.sparescreen.plist"


def launch_command(extra_args):
    """How to start this same installation in the background, with the user's options."""
    if getattr(sys, "frozen", False):  # a packaged executable (PyInstaller)
        base = [sys.executable]
    else:
        python = Path(sys.executable)
        windowless = python.with_name("pythonw.exe")  # no console window on Windows
        base = [str(windowless if sys.platform == "win32" and windowless.exists() else python), "-m", "sparescreen"]
    return base + list(extra_args) + ["--background"]


def enable(extra_args=()):
    command = launch_command(extra_args)
    if sys.platform == "win32":
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, APP, 0, winreg.REG_SZ, subprocess.list2cmdline(command))
    elif sys.platform == "darwin":
        LAUNCH_AGENT.parent.mkdir(parents=True, exist_ok=True)
        with open(LAUNCH_AGENT, "wb") as f:
            plistlib.dump({"Label": LAUNCH_AGENT.stem, "ProgramArguments": command, "RunAtLoad": True}, f)
    else:
        DESKTOP_FILE.parent.mkdir(parents=True, exist_ok=True)
        DESKTOP_FILE.write_text(
            "[Desktop Entry]\nType=Application\nName=SpareScreen\n"
            "Comment=Old phone as a PC dashboard\n"
            f"Exec={' '.join(shlex.quote(part) for part in command)}\n"
            "X-GNOME-Autostart-enabled=true\nNoDisplay=true\n",
            encoding="utf-8",
        )
    return command


def disable():
    if sys.platform == "win32":
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, APP)
        except FileNotFoundError:
            pass
    else:
        path = LAUNCH_AGENT if sys.platform == "darwin" else DESKTOP_FILE
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


def status():
    """The registered command line, or None when autostart is off."""
    if sys.platform == "win32":
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                return winreg.QueryValueEx(key, APP)[0]
        except FileNotFoundError:
            return None
    path = LAUNCH_AGENT if sys.platform == "darwin" else DESKTOP_FILE
    if not path.exists():
        return None
    if sys.platform == "darwin":
        with open(path, "rb") as f:
            return " ".join(plistlib.load(f).get("ProgramArguments", []))
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("Exec="):
            return line[len("Exec="):]
    return str(path)
