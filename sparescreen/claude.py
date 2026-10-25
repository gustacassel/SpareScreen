"""Claude Code usage, read from the local files.

- ~/.claude/sessions/<pid>.json: one per open session, with name, folder and status.
- ~/.claude/projects/**/*.jsonl: the conversation history; each response carries its token usage.
- ~/.sparescreen/claude-limits.json: 5-hour and weekly windows, written by our status line
  (sparescreen/statusline.py), because Claude Code only hands those numbers to it, or by
  the optional limits check (sparescreen/claude_probe.py) for desktop/IDE users.

The first two are internal Claude Code formats and may change between
versions, so everything here tolerates missing fields.
"""

from __future__ import annotations

import glob
import json
import os
import re
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import psutil

from .claude_probe import PROBE_DIR, LimitsProbe
from .shapes import Json
from .statusline import load_limits

BUCKET = 15 * 60          # tokens are summed in 15-minute blocks
KEEP = 8 * 24 * 3600      # keep a bit more than the weekly window
WEEK = 7 * 24 * 3600


LIMIT_LABELS = {"five_hour": ("5 hours", False), "seven_day": ("Week", True)}
RECENT = 15 * 60  # a session touched this recently means Claude is "in use"


def limit_label(key: str) -> tuple[str, bool] | None:
    """('5 hours', weekly?) for a limit key; model-specific weekly limits such as
    'seven_day_opus' become 'Week · Opus'. Unknown keys return None."""
    if key in LIMIT_LABELS:
        return LIMIT_LABELS[key]
    if key.startswith("seven_day_"):
        return "Week · " + key[len("seven_day_"):].replace("_", " ").title(), True
    return None


def claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def window_label(minutes: float) -> str:
    """Usage window length as a short label: 299 -> '5 hours', 10079 -> 'Week'."""
    hours = minutes / 60
    if hours >= 6.5 * 24:
        return "Week"
    if hours >= 24:
        days = round(hours / 24)
        return "1 day" if days == 1 else f"{days} days"
    return f"{round(hours)} hours"


def _same_folder(a: str | Path | None, b: str | Path) -> bool:
    if not a:
        return False
    return os.path.normcase(os.path.abspath(str(a))) == os.path.normcase(os.path.abspath(str(b)))


def model_label(model: str | None) -> str:
    """'claude-opus-5-5' -> 'Opus 5.5'; 'claude-opus-5' -> 'Opus 5'; anything else is shown as it is."""
    match = re.match(r"claude-([a-z]+)-(\d+)(?:-(\d{1,2}))?(?:\b|$)", model or "")
    if match:
        version = match.group(2) + ("." + match.group(3) if match.group(3) else "")
        return f"{match.group(1).title()} {version}"
    return model or "?"


class ClaudeSource:
    """Usage limits, tokens (today and this week per model) and open sessions.

    Returns the same shape as the other AI tool sources (see codex.py)."""

    name = "claude"

    def __init__(self, home: str | Path | None = None, token_refresh: float = 5,
                 probe: LimitsProbe | None = None, probe_enabled: Callable[[], bool] | None = None) -> None:
        """`probe` (LimitsProbe) checks the limits headlessly when `probe_enabled()` is true."""
        self.home = Path(home) if home else claude_home()
        self.probe = probe
        self.probe_enabled = probe_enabled or (lambda: False)
        self.token_refresh = token_refresh
        self._token_at: float = 0
        self._offsets: dict[str, int] = {}  # file -> how many bytes have been read already
        # (message id, requestId) -> block; the same response shows up on several lines
        self._seen: dict[tuple[Any, Any], int] = {}
        # (block, model) -> input, output, cache, responses
        self._buckets: defaultdict[tuple[int, str], list[int]] = defaultdict(lambda: [0, 0, 0, 0])

    def read(self) -> Json:
        if not self.home.is_dir():
            return {"installed": False}
        now = time.time()
        if now - self._token_at >= self.token_refresh:
            self._scan_tokens(now)
            self._token_at = now
        sessions = self._sessions()
        saved = load_limits()
        probing = bool(self.probe and self.probe_enabled())
        if probing and self.probe:
            active = any(s["status"] == "busy" or now - s["since"] < RECENT for s in sessions)
            self.probe.maybe_run(active, saved.get("updated_at") if saved else None)
        limits = self._limits(saved, now)
        weekly = next((w for w in limits if w["weekly"] and not w["renewed"]), None)
        week_start = weekly["resets_at"] - WEEK if weekly else now - WEEK
        midnight = datetime.combine(datetime.now().date(), datetime.min.time()).timestamp()
        return {
            "installed": True,
            "name": "Claude Code",
            "limits": limits,
            "limits_updated": saved.get("updated_at") if saved else None,
            "limits_hint": None if saved else self._hint(probing),
            "today": self._sum(lambda block, model: block >= midnight - BUCKET + 1),
            "week_models": self._models_since(week_start),
            "sessions": sessions,
        }

    def _hint(self, probing: bool) -> str:
        if probing and self.probe and not self.probe.available:
            return "The claude command was not found, so limits can't be checked."
        if probing:
            return "Checking limits while you use Claude Code..."
        return "No limits yet: turn on \"Check Claude limits\" in settings, or use Claude Code in a terminal."

    # Limits (status line) ---------------------------------------------------

    @staticmethod
    def _limits(saved: Json | None, now: float) -> list[Json]:
        windows: list[Json] = []
        for key, window in ((saved or {}).get("rate_limits") or {}).items():
            found = limit_label(key)
            if not found or not isinstance(window, dict) or window.get("resets_at") is None:
                continue
            renewed = window["resets_at"] <= now  # the window rolled over after the last reading
            label, weekly = found
            windows.append({
                "label": label,
                "percent": None if renewed else window.get("used_percentage"),
                "resets_at": window["resets_at"],
                "renewed": renewed,
                "weekly": weekly,
            })
        windows.sort(key=lambda w: (w["weekly"], w["label"] != "Week"))  # 5 hours, week, then per model
        return windows

    def _models_since(self, start: float) -> list[Json]:
        tokens: Counter[str] = Counter()
        for (block, model), (inp, out, cache, _) in self._buckets.items():
            if block >= start - BUCKET + 1:
                tokens[model] += inp + out + cache
        return [{"model": m, "label": model_label(m), "tokens": t} for m, t in tokens.most_common(3)]

    # Tokens -----------------------------------------------------------------

    def _sum(self, keep: Callable[[int, str], bool]) -> Json:
        total: Json = {"input": 0, "output": 0, "cache_read": 0, "responses": 0}
        models: Counter[str] = Counter()
        for (block, model), (inp, out, cache, responses) in self._buckets.items():
            if keep(block, model):
                total["input"] += inp
                total["output"] += out
                total["cache_read"] += cache
                total["responses"] += responses
                models[model] += responses
        total["models"] = dict(models.most_common())
        return total

    def _scan_tokens(self, now: float) -> None:
        cutoff = now - KEEP
        for key in [k for k in self._buckets if k[0] < cutoff]:
            del self._buckets[key]
        self._seen = {k: b for k, b in self._seen.items() if b >= cutoff}

        pattern = str(self.home / "projects" / "**" / "*.jsonl")
        for path in glob.glob(pattern, recursive=True):
            try:
                st = os.stat(path)
            except OSError:
                continue
            if st.st_mtime < cutoff:
                continue
            offset = self._offsets.get(path, 0)
            if st.st_size < offset:  # file was rewritten: read it again
                offset = 0
            if st.st_size == offset:
                continue
            with open(path, "rb") as f:
                f.seek(offset)
                chunk = f.read()
            end = chunk.rfind(b"\n")  # the last line may be half-written
            if end < 0:
                continue
            self._offsets[path] = offset + end + 1
            for line in chunk[:end].splitlines():
                if b'"usage"' in line and b'"assistant"' in line:
                    self._add(line, cutoff)

    def _add(self, line: bytes, cutoff: float) -> None:
        try:
            entry = json.loads(line)
        except ValueError:
            return
        if entry.get("type") != "assistant":
            return
        msg = entry.get("message") or {}
        usage = msg.get("usage")
        model = msg.get("model") or "?"
        if not usage or model == "<synthetic>":
            return
        try:
            stamp = datetime.fromisoformat(entry["timestamp"].replace("Z", "+00:00")).timestamp()
        except (KeyError, ValueError):
            return
        if stamp < cutoff:
            return
        block = int(stamp // BUCKET * BUCKET)
        key = (msg.get("id"), entry.get("requestId"))
        if key in self._seen:
            return
        self._seen[key] = block

        b = self._buckets[(block, model)]
        b[0] += (usage.get("input_tokens") or 0) + (usage.get("cache_creation_input_tokens") or 0)
        b[1] += usage.get("output_tokens") or 0
        b[2] += usage.get("cache_read_input_tokens") or 0
        b[3] += 1

    # Open sessions ----------------------------------------------------------

    def _sessions(self) -> list[Json]:
        sessions: list[Json] = []
        for file in (self.home / "sessions").glob("*.json"):
            try:
                info = json.loads(file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            pid = info.get("pid")
            if not pid or not psutil.pid_exists(pid):  # session file for one that already closed
                continue
            if _same_folder(info.get("cwd"), PROBE_DIR):  # our own limits check, not a real session
                continue
            project = Path(info.get("cwd") or "").name
            since = info.get("statusUpdatedAt") or info.get("updatedAt") or info.get("startedAt") or 0
            sessions.append({
                "id": info.get("sessionId") or str(pid),
                "name": info.get("name") or project or info.get("sessionId", "")[:8],
                "project": project,
                "status": info.get("status") or "?",
                "since": since / 1000,
            })
        # Busy ones first, then the most recent.
        sessions.sort(key=lambda s: (s["status"] != "busy", -s["since"]))
        return sessions
