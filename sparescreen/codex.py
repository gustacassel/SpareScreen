"""OpenAI Codex CLI usage, read from its local session files.

Codex writes every session to $CODEX_HOME/sessions/YYYY/MM/DD/rollout-*.jsonl
(CODEX_HOME defaults to ~/.codex). Each line is {"timestamp", "type", "payload"}:

- "session_meta": the session id and working folder.
- "turn_context": the model in use from that point on.
- "event_msg" with payload type:
  - "token_count": cumulative token usage for the session ("info.total_token_usage")
    and the plan's usage limits ("rate_limits.primary/secondary": used_percent,
    window_minutes, resets_at or, in older versions, resets_in_seconds).
  - "turn_started" / "turn_complete" / "turn_aborted" (older: "task_*"):
    whether the session is working.
  - "user_message": what was asked (the first one names the session).

These are Codex's internal formats and may change between versions, so every
field is optional here.
"""

from __future__ import annotations

import glob
import json
import os
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .claude import window_label, model_label
from .shapes import Json

BUCKET = 15 * 60
KEEP = 8 * 24 * 3600
WEEK = 7 * 24 * 3600
SHOW_SESSIONS_FOR = 12 * 3600   # sessions touched in the last 12 h
STALE_TURN = 30 * 60            # a turn "started" this long ago without news is probably dead
BUSY_EVENTS = {"turn_started", "task_started"}
IDLE_EVENTS = {"turn_complete", "task_complete", "turn_aborted"}


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def _epoch(stamp: Any) -> float | None:
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return None


class _SessionFile:
    """What we know about one rollout file so far (it is read incrementally)."""

    def __init__(self) -> None:
        self.offset = 0
        self.id: str | None = None
        self.cwd = ""
        self.title: str | None = None
        self.model = "?"
        self.status = "idle"
        self.since: float = 0
        self.last_totals: tuple[int, int, int] | None = None  # previous cumulative usage, to turn totals into deltas


class CodexSource:
    """Usage limits, tokens and recent sessions of the Codex CLI."""

    name = "codex"

    def __init__(self, home: str | Path | None = None, refresh: float = 5) -> None:
        self.home = Path(home) if home else codex_home()
        self.refresh = refresh
        self._at: float = 0
        self._files: dict[str, _SessionFile] = {}
        # (bucket, model) -> input, output, cached, responses
        self._buckets: defaultdict[tuple[int, str], list[int]] = defaultdict(lambda: [0, 0, 0, 0])
        self._limits: tuple[float, Json] | None = None  # (timestamp, rate_limits)

    def read(self) -> Json:
        if not (self.home / "sessions").is_dir():
            return {"installed": False}
        now = time.time()
        if now - self._at >= self.refresh:
            self._scan(now)
            self._at = now
        limits = self._limit_windows(now)
        weekly = next((w for w in limits if w["weekly"] and not w["renewed"]), None)
        week_start = weekly["resets_at"] - WEEK if weekly else now - WEEK
        midnight = datetime.combine(datetime.now().date(), datetime.min.time()).timestamp()
        return {
            "installed": True,
            "name": "Codex",
            "limits": limits,
            "limits_updated": self._limits[0] if self._limits else None,
            "limits_hint": None if limits else "Limits show up after your next Codex message.",
            "today": self._sum(lambda block: block >= midnight - BUCKET + 1),
            "week_models": self._models_since(week_start),
            "sessions": self._sessions(now),
        }

    # Reading -------------------------------------------------------------------

    def _scan(self, now: float) -> None:
        cutoff = now - KEEP
        for key in [k for k in self._buckets if k[0] < cutoff]:
            del self._buckets[key]
        pattern = str(self.home / "sessions" / "**" / "rollout-*.jsonl")
        for path in glob.glob(pattern, recursive=True):
            try:
                st = os.stat(path)
            except OSError:
                continue
            if st.st_mtime < cutoff:
                continue
            info = self._files.setdefault(path, _SessionFile())
            if st.st_size < info.offset:  # rewritten: start over
                info = self._files[path] = _SessionFile()
            if st.st_size == info.offset:
                continue
            with open(path, "rb") as f:
                f.seek(info.offset)
                chunk = f.read()
            end = chunk.rfind(b"\n")  # the last line may still be half written
            if end < 0:
                continue
            info.offset += end + 1
            for line in chunk[:end].splitlines():
                self._line(info, line, cutoff)

    def _line(self, info: _SessionFile, line: bytes, cutoff: float) -> None:
        try:
            entry = json.loads(line)
        except ValueError:
            return
        kind = entry.get("type")
        payload = entry.get("payload") or {}
        stamp = _epoch(entry.get("timestamp"))
        if kind == "session_meta":
            info.id = payload.get("id") or info.id
            info.cwd = payload.get("cwd") or info.cwd
        elif kind == "turn_context":
            info.model = payload.get("model") or info.model
        elif kind == "event_msg":
            event = payload.get("type")
            if event in BUSY_EVENTS or event in IDLE_EVENTS:
                info.status = "busy" if event in BUSY_EVENTS else "idle"
                info.since = stamp or info.since
            elif event == "user_message" and info.title is None:
                text = " ".join(str(payload.get("message") or "").split())
                info.title = text[:80] or None
            elif event == "token_count":
                self._token_count(info, payload, stamp, cutoff)

    def _token_count(self, info: _SessionFile, payload: Json, stamp: float | None, cutoff: float) -> None:
        limits = payload.get("rate_limits")
        if isinstance(limits, dict) and stamp and (self._limits is None or stamp >= self._limits[0]):
            self._limits = (stamp, limits)
        usage = (payload.get("info") or {}).get("total_token_usage")
        if not isinstance(usage, dict) or not stamp:
            return
        totals = (usage.get("input_tokens") or 0, usage.get("cached_input_tokens") or 0,
                  usage.get("output_tokens") or 0)
        previous = info.last_totals or (0, 0, 0)
        info.last_totals = totals
        delta = [max(0, now - before) for now, before in zip(totals, previous)]
        if stamp < cutoff or not any(delta):
            return
        b = self._buckets[(int(stamp // BUCKET * BUCKET), info.model)]
        b[0] += max(0, delta[0] - delta[1])  # input_tokens includes the cached part
        b[1] += delta[2]
        b[2] += delta[1]
        b[3] += 1

    # Summaries -----------------------------------------------------------------

    def _limit_windows(self, now: float) -> list[Json]:
        if not self._limits:
            return []
        stamp, limits = self._limits
        windows: list[Json] = []
        for key in ("primary", "secondary"):
            w = limits.get(key)
            if not isinstance(w, dict) or w.get("used_percent") is None:
                continue
            resets_at = w.get("resets_at")
            if resets_at is None and w.get("resets_in_seconds") is not None:
                resets_at = stamp + w["resets_in_seconds"]
            minutes = w.get("window_minutes")
            renewed = resets_at is not None and resets_at <= now
            windows.append({
                "label": window_label(minutes) if minutes else ("5 hours" if key == "primary" else "Week"),
                "percent": None if renewed else w["used_percent"],
                "resets_at": resets_at,
                "renewed": renewed,
                "weekly": bool(minutes and minutes >= 6 * 24 * 60) or (not minutes and key == "secondary"),
            })
        return windows

    def _sum(self, keep: Callable[[int], bool]) -> Json:
        total: Json = {"input": 0, "output": 0, "cache_read": 0, "responses": 0}
        models: Counter[str] = Counter()
        for (block, model), (inp, out, cached, responses) in self._buckets.items():
            if keep(block):
                total["input"] += inp
                total["output"] += out
                total["cache_read"] += cached
                total["responses"] += responses
                models[model] += responses
        total["models"] = dict(models.most_common())
        return total

    def _models_since(self, start: float) -> list[Json]:
        tokens: Counter[str] = Counter()
        for (block, model), (inp, out, cached, _) in self._buckets.items():
            if block >= start - BUCKET + 1:
                tokens[model] += inp + out + cached
        return [{"model": m, "label": model_label(m), "tokens": t} for m, t in tokens.most_common(3)]

    def _sessions(self, now: float) -> list[Json]:
        sessions: list[Json] = []
        for path, info in self._files.items():
            try:
                touched = os.stat(path).st_mtime
            except OSError:
                continue
            if now - touched > SHOW_SESSIONS_FOR:
                continue
            status = info.status
            if status == "busy" and now - touched > STALE_TURN:
                status = "idle"  # Codex was closed mid-turn
            project = Path(info.cwd).name if info.cwd else ""
            sessions.append({
                "id": "codex:" + (info.id or Path(path).stem),
                "name": info.title or project or "Codex session",
                "project": project,
                "status": status,
                "since": info.since or touched,
            })
        sessions.sort(key=lambda s: (s["status"] != "busy", -s["since"]))
        return sessions[:8]
