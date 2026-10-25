"""Opens a local page in its own app window: Edge or Chrome with --app (no tabs, no
address bar), so the PC window looks like a program. Falls back to the default browser.

Windows always has Edge; on Linux and macOS any Chromium-based browser works.
A separate browser profile in ~/.sparescreen/window keeps the window's size and
position and stays out of the user's own browsing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Iterator, Optional

PROFILE = Path.home() / ".sparescreen" / "window"
SIZE = "560,780"


def _windows_browsers() -> Iterator[str]:
    for env in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if base:
            yield os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe")
            yield os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")


def find_browser(platform: Optional[str] = None) -> Optional[str]:
    platform = platform or sys.platform
    if platform == "win32":
        return next((path for path in _windows_browsers() if os.path.isfile(path)), None)
    if platform == "darwin":
        for app in ("Google Chrome", "Microsoft Edge", "Chromium", "Brave Browser"):
            path = f"/Applications/{app}.app/Contents/MacOS/{app}"
            if os.path.isfile(path):
                return path
        return None
    names = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "brave-browser")
    return next((shutil.which(name) for name in names if shutil.which(name)), None)


def command(browser: str, url: str) -> list[str]:
    return [browser, f"--app={url}", f"--window-size={SIZE}", f"--user-data-dir={PROFILE}",
            "--no-first-run", "--no-default-browser-check"]


def open_window(url: str) -> bool:
    """Opens `url` as an app window; True if it worked, False if it fell back to a browser tab."""
    browser = find_browser()
    if browser:
        try:
            subprocess.Popen(command(browser, url), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, close_fds=True)
            return True
        except OSError:
            pass
    webbrowser.open(url)
    return False
