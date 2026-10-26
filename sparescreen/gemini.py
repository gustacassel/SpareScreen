"""Google Gemini CLI usage, read from its local chat files.

Gemini CLI records every chat in $GEMINI_CLI_HOME/.gemini/tmp/<project>/chats/
(GEMINI_CLI_HOME defaults to the user's home folder). <project> is a short name kept in
~/.gemini/projects.json ({"projects": {"<project folder>": "<short name>"}}); older
versions used a hash of the folder.

- Current versions append to session-<date>-<id>.jsonl, one JSON record per line: the
  session's metadata ({"sessionId", "startTime", ...}), messages ({"id", "timestamp",
  "type": user|gemini|info|error|warning, "content", "model", "tokens", "toolCalls"}),
  "$set" updates (e.g. the session "summary") and "$patch" edits. A message is written
  again, whole and with the same id, every time it changes (its tokens arrive later),
  so tokens are counted once per message id.
- Older versions rewrote one session-*.json file: {"sessionId", "messages": [...]}.
- Subagents get their own file in chats/<parent session>/: their tokens count, but they
  aren't listed as sessions.

"tokens" is {"input", "output", "cached", "thoughts", "tool", "total"}; input includes the
cached part, and thinking is billed as output. Gemini CLI doesn't keep its usage limits
on disk, so the card shows tokens and sessions only.

Whether a session is working isn't written down either. It's worked out from the last
message: a question, or an answer that called tools, means it's working. An answer with
only text usually ends the turn, but Gemini CLI writes the text before running the tools
it asked for and adds them only once they finish, so the session counts as finished
after SETTLE seconds without anything new.

These are Gemini CLI's internal formats and may change between versions, so every field
is optional here.
"""

from __future__ import annotations

import glob
import json
import os
import re
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .codex import (BUCKET, KEEP, SHOW_SESSIONS_FOR, STALE_TURN, WEEK, _epoch, models_since,
                    sum_buckets)
from .shapes import Json

SETTLE = 20  # seconds a text answer stays the last word before the turn counts as over


def gemini_home() -> Path:
    return Path(os.environ.get("GEMINI_CLI_HOME") or Path.home()) / ".gemini"


def _text(content: Any) -> str:
    """A message's content (a string, a part or a list of parts) as plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        text = content.get("text")
        return text if isinstance(text, str) else ""
    if isinstance(content, list):
        return " ".join(_text(part) for part in content)
    return ""


class _ChatFile:
    """What we know about one chat file so far (.jsonl files are read incrementally)."""

    def __init__(self, subagent: bool) -> None:
        self.offset = 0
        self.subagent = subagent
        self.id: str | None = None
        self.title: str | None = None
        self.summary: str | None = None
        self.last = "none"  # the last message: question, tools, text, cancelled or none
        self.since: float = 0


class GeminiSource:
    """Tokens (today and this week per model) and recent sessions of the Gemini CLI."""

    name = "gemini"

    def __init__(self, home: str | Path | None = None, refresh: float = 5) -> None:
        self.home = Path(home) if home else gemini_home()
        self.refresh = refresh
        self._at: float = 0
        self._files: dict[str, _ChatFile] = {}
        self._stamps: dict[str, tuple[float, int]] = {}  # .json file -> (mtime, size) when last read
        self._buckets: defaultdict[tuple[int, str], list[int]] = defaultdict(lambda: [0, 0, 0, 0])
        self._projects: dict[str, str] = {}  # short name -> project folder name
        # message id -> ((input, output, cached), when) already counted: messages are written
        # again when they change, and a resumed or converted session is written whole again.
        self._counted: dict[str, tuple[tuple[int, int, int], float]] = {}

    def read(self) -> Json:
        if not (self.home / "tmp").is_dir():
            return {"installed": False}
        now = time.time()
        if now - self._at >= self.refresh:
            self._scan(now)
            self._at = now
        midnight = datetime.combine(datetime.now().date(), datetime.min.time()).timestamp()
        return {
            "installed": True,
            "name": "Gemini CLI",
            "limits": [],
            "limits_updated": None,
            "limits_hint": "Gemini CLI doesn't save its limits on this PC.",
            "today": sum_buckets(self._buckets, lambda block: block >= midnight - BUCKET + 1),
            "week_models": models_since(self._buckets, now - WEEK),
            "sessions": self._sessions(now),
        }

    # Reading -------------------------------------------------------------------

    def _scan(self, now: float) -> None:
        cutoff = now - KEEP
        for block in [k for k in self._buckets if k[0] < cutoff]:
            del self._buckets[block]
        for key in [k for k, (_, at) in self._counted.items() if at < cutoff]:
            del self._counted[key]
        self._projects = self._read_projects()
        chats = str(self.home / "tmp" / "*" / "chats")
        for path in glob.glob(chats + "/*.json*") + glob.glob(chats + "/*/*.jsonl"):
            if not path.endswith((".json", ".jsonl")):
                continue
            try:
                st = os.stat(path)
            except OSError:
                continue
            if st.st_mtime < cutoff:
                continue
            subagent = Path(path).parent.name != "chats"
            info = self._files.setdefault(path, _ChatFile(subagent))
            if path.endswith(".jsonl"):
                self._read_jsonl(path, info, st.st_size, cutoff)
            elif self._stamps.get(path) != (st.st_mtime, st.st_size):
                self._stamps[path] = (st.st_mtime, st.st_size)
                self._read_json(path, info, cutoff)

    def _read_projects(self) -> dict[str, str]:
        try:
            data = json.loads((self.home / "projects.json").read_text(encoding="utf-8"))
            projects = data.get("projects") if isinstance(data, dict) else None
            return {slug: Path(folder).name for folder, slug in (projects or {}).items()
                    if isinstance(folder, str) and isinstance(slug, str)}
        except (OSError, ValueError, AttributeError):
            return {}

    def _read_jsonl(self, path: str, info: _ChatFile, size: int, cutoff: float) -> None:
        if size < info.offset:  # rewritten (a resumed session): read again; `_counted` avoids double counts
            info.offset = 0
        if size == info.offset:
            return
        try:
            with open(path, "rb") as f:
                f.seek(info.offset)
                chunk = f.read()
        except OSError:
            return
        end = chunk.rfind(b"\n")  # the last line may still be half written
        if end < 0:
            return
        info.offset += end + 1
        for line in chunk[:end].splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                self._record(info, record, cutoff)

    def _read_json(self, path: str, info: _ChatFile, cutoff: float) -> None:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return  # probably being rewritten: read again next time
        if not isinstance(data, dict):
            return
        self._record(info, {k: v for k, v in data.items() if k != "messages"}, cutoff)
        for message in data.get("messages") or []:
            if isinstance(message, dict):
                self._record(info, message, cutoff)

    def _record(self, info: _ChatFile, record: Json, cutoff: float) -> None:
        if "$set" in record:
            update = record["$set"]
            if isinstance(update, dict) and isinstance(update.get("summary"), str):
                info.summary = update["summary"]
            return
        if "$patch" in record or "$rewindTo" in record:
            return  # edits to content: nothing we show
        kind = record.get("type")
        if kind is None:  # the session's metadata
            info.id = record.get("sessionId") or info.id
            if isinstance(record.get("summary"), str):
                info.summary = record["summary"]
            return
        stamp = _epoch(record.get("timestamp"))
        if kind == "user":
            text = " ".join(_text(record.get("content")).split())
            if text.startswith("/"):
                return  # a command for Gemini CLI itself, not a question
            if info.title is None and text:
                info.title = text[:80]
            self._last(info, "question", stamp)
        elif kind == "gemini":
            calls = [c for c in record.get("toolCalls") or [] if isinstance(c, dict)]
            content = record.get("content")
            asked = isinstance(content, list) and any(isinstance(p, dict) and "functionCall" in p for p in content)
            if calls and all(c.get("status") == "cancelled" for c in calls):
                self._last(info, "cancelled", stamp)
            else:
                self._last(info, "tools" if calls or asked else "text", stamp)
            self._tokens(record, stamp, cutoff)
        elif kind in ("info", "error", "warning") and info.last in ("question", "tools"):
            self._last(info, "cancelled", stamp)  # e.g. "Request cancelled."

    @staticmethod
    def _last(info: _ChatFile, last: str, stamp: float | None) -> None:
        if last != info.last:
            info.since = stamp or info.since
        info.last = last

    def _tokens(self, record: Json, stamp: float | None, cutoff: float) -> None:
        tokens = record.get("tokens")
        key = record.get("id")
        if not isinstance(tokens, dict) or not isinstance(key, str) or not stamp or stamp < cutoff:
            return

        def count(name: str) -> int:
            value = tokens.get(name)
            return int(value) if isinstance(value, (int, float)) and value > 0 else 0

        cached = count("cached")
        now = (max(0, count("input") - cached), count("output") + count("thoughts"), cached)
        before = self._counted[key][0] if key in self._counted else None
        self._counted[key] = (now, stamp)
        delta = [max(0, a - b) for a, b in zip(now, before or (0, 0, 0))]
        if not any(delta):
            return
        model = record.get("model")
        b = self._buckets[(int(stamp // BUCKET * BUCKET), model if isinstance(model, str) else "?")]
        b[0] += delta[0]
        b[1] += delta[1]
        b[2] += delta[2]
        if before is None:
            b[3] += 1

    # Summaries -----------------------------------------------------------------

    def _project(self, path: str) -> str:
        slug = Path(path).parent.parent.name
        if Path(path).parent.name != "chats":
            slug = Path(path).parent.parent.parent.name
        if slug in self._projects:
            return self._projects[slug]
        return "" if re.fullmatch(r"[0-9a-f]{32,}", slug) else slug  # an old hash says nothing

    def _sessions(self, now: float) -> list[Json]:
        sessions: list[Json] = []
        for path, info in self._files.items():
            if info.subagent:
                continue
            try:
                touched = os.stat(path).st_mtime
            except OSError:
                continue
            if now - touched > SHOW_SESSIONS_FOR or (info.title is None and info.summary is None):
                continue  # too old, or opened and closed without a question
            if info.last in ("question", "tools"):
                status = "busy" if now - touched < STALE_TURN else "idle"  # or closed mid-answer
            elif info.last == "text":
                status = "busy" if now - touched < SETTLE else "idle"
            else:
                status = "idle"
            project = self._project(path)
            sessions.append({
                "id": "gemini:" + (info.id or Path(path).stem),
                "name": info.summary or info.title or project or "Gemini session",
                "project": project,
                "status": status,
                "since": info.since or touched,
            })
        sessions.sort(key=lambda s: (s["status"] != "busy", -s["since"]))
        return sessions[:8]
