"""Claude Code usage, read from the local files.

- ~/.claude/sessions/<pid>.json: one per open session, with name, folder and status.
- ~/.claude/projects/**/*.jsonl: the conversation history; each response carries its token usage.
- ~/.sparescreen/claude-limits.json: 5-hour and weekly windows, written by our status line
  (sparescreen/statusline.py), because Claude Code only hands those numbers to it.

The first two are internal Claude Code formats and may change between
versions, so everything here tolerates missing fields.
"""

import glob
import json
import os
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import psutil

from .statusline import load_limits

BUCKET = 15 * 60          # tokens are summed in 15-minute blocks
KEEP = 8 * 24 * 3600      # keep a bit more than the weekly window
WEEK = 7 * 24 * 3600


def claude_home():
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


class ClaudeSource:
    """Usage limits, tokens (today and Fable this week) and open sessions."""

    name = "claude"

    def __init__(self, home=None, token_refresh=5):
        self.home = Path(home) if home else claude_home()
        self.token_refresh = token_refresh
        self._token_at = 0
        self._offsets = {}  # file -> how many bytes have been read already
        self._seen = {}     # (message id, requestId) -> block; the same response shows up on several lines
        self._buckets = defaultdict(lambda: [0, 0, 0, 0])  # (block, model) -> input, output, cache, responses

    def read(self):
        now = time.time()
        if now - self._token_at >= self.token_refresh:
            self._scan_tokens(now)
            self._token_at = now
        limits = self._limits(now)
        week = limits.get("seven_day") if limits else None
        week_start = week["resets_at"] - WEEK if week else now - WEEK
        midnight = datetime.combine(datetime.now().date(), datetime.min.time()).timestamp()
        return {
            "limits": limits,
            "today": self._sum(lambda block, model: block >= midnight - BUCKET + 1),
            "fable_week": {
                **self._sum(lambda block, model: "fable" in model and block >= week_start - BUCKET + 1),
                "since": week_start,
            },
            "sessions": self._sessions(),
        }

    # Limits (status line) ---------------------------------------------------

    @staticmethod
    def _limits(now):
        saved = load_limits()
        if not saved:
            return None
        windows = {}
        for key, window in (saved.get("rate_limits") or {}).items():
            if not isinstance(window, dict) or window.get("resets_at") is None:
                continue
            renewed = window["resets_at"] <= now  # the window rolled over after the last reading
            windows[key] = {
                "percent": None if renewed else window.get("used_percentage"),
                "resets_at": window["resets_at"],
                "renewed": renewed,
            }
        windows["updated_at"] = saved.get("updated_at")
        return windows

    # Tokens -----------------------------------------------------------------

    def _sum(self, keep):
        total = {"input": 0, "output": 0, "cache_read": 0, "responses": 0}
        models = Counter()
        for (block, model), (inp, out, cache, responses) in self._buckets.items():
            if keep(block, model):
                total["input"] += inp
                total["output"] += out
                total["cache_read"] += cache
                total["responses"] += responses
                models[model] += responses
        total["models"] = dict(models.most_common())
        return total

    def _scan_tokens(self, now):
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

    def _add(self, line, cutoff):
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

    def _sessions(self):
        sessions = []
        for file in (self.home / "sessions").glob("*.json"):
            try:
                info = json.loads(file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            pid = info.get("pid")
            if not pid or not psutil.pid_exists(pid):  # session file for one that already closed
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
