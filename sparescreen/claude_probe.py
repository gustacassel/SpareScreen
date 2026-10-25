"""Optional check of Claude Code's usage limits for people who don't use the terminal.

Claude Code only hands the 5-hour and weekly limits to its status line, which the
desktop app and IDE extensions don't run. In headless mode (`claude -p` with
stream-json output) it also emits a documented `rate_limit_event` with the same
numbers. When the user turns this on, we send a tiny request to the cheapest model
every few minutes, and only while Claude Code is in use, so we never start a new
5-hour window on our own. The result is saved in the same file the status line
writes (see statusline.py).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
from pathlib import Path

from .shapes import Json
from .statusline import save_limits

PROBE_DIR = Path.home() / ".sparescreen" / "probe"  # working folder, so its session is easy to hide
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
COMMAND = [
    "-p", "Reply with just OK",
    "--output-format", "stream-json", "--verbose",
    "--model", "haiku", "--max-turns", "1",
    "--no-session-persistence", "--strict-mcp-config", "--tools", "",
]


def limits_from_event(event: Json) -> Json:
    """rate_limit_event -> the status line's rate_limits shape:
    {"five_hour": {"used_percentage": 19.0, "resets_at": 1792893600}, ...}."""
    info = event.get("rate_limit_info") or {}
    windows = info.get("unifiedWindows") or {}
    limits: Json = {}
    for key, window in windows.items():
        if not isinstance(window, dict) or window.get("utilization") is None:
            continue
        limits[key] = {"used_percentage": round(window["utilization"] * 100, 1),
                       "resets_at": window.get("resetsAt")}
    return limits


class LimitsProbe:
    def __init__(self, interval: float = 600, timeout: float = 120, exe: str | None = None) -> None:
        self.interval = interval
        self.timeout = timeout
        self.exe = exe if exe is not None else shutil.which("claude")
        self.last_attempt: float = 0
        self.last_error: str | None = None
        self._running = False

    @property
    def available(self) -> bool:
        return bool(self.exe)

    def maybe_run(self, active: bool, updated_at: float | None) -> bool:
        """Start a check in the background if Claude is in use and the numbers are old."""
        now = time.time()
        fresh = updated_at is not None and now - updated_at < self.interval
        if not self.exe or not active or fresh or self._running or now - self.last_attempt < self.interval:
            return False
        self.last_attempt = now
        self._running = True
        threading.Thread(target=self._run, name="claude-limits", daemon=True).start()
        return True

    def _run(self) -> None:
        try:
            assert self.exe  # maybe_run only starts a check when there is one
            PROBE_DIR.mkdir(parents=True, exist_ok=True)
            result = subprocess.run(
                [self.exe, *COMMAND], cwd=PROBE_DIR, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=self.timeout, creationflags=_NO_WINDOW,
            )
            for line in result.stdout.splitlines():
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get("type") == "rate_limit_event":
                    limits = limits_from_event(event)
                    if limits:
                        save_limits(limits)
                        self.last_error = None
                        return
            self.last_error = "no limits in Claude's answer"
        except (OSError, subprocess.SubprocessError) as exc:
            self.last_error = str(exc)
        finally:
            self._running = False
