"""Claude Code status line that passes the usage limits on to the dashboard.

Configured in ~/.claude/settings.json ("statusLine"). Claude Code runs this
command on every update and sends the session data as JSON on stdin; the
`rate_limits` field (5-hour and weekly windows) only exists on Pro/Max plans.
We save that field to a file that the dashboard agent reads.
"""

import json
import os
import sys
import time
from pathlib import Path

LIMITS_FILE = Path.home() / ".sparescreen" / "claude-limits.json"


def save_limits(limits):
    LIMITS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = LIMITS_FILE.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps({"updated_at": time.time(), "rate_limits": limits}), encoding="utf-8")
    os.replace(tmp, LIMITS_FILE)  # atomic swap: the agent never reads a half-written file


def load_limits():
    try:
        return json.loads(LIMITS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def status_text(data):
    parts = [(data.get("model") or {}).get("display_name") or "Claude"]
    ctx = (data.get("context_window") or {}).get("used_percentage")
    if ctx is not None:
        parts.append(f"ctx {ctx:.0f}%")
    limits = data.get("rate_limits") or {}
    for key, label in (("five_hour", "5h"), ("seven_day", "week")):
        pct = (limits.get(key) or {}).get("used_percentage")
        if pct is not None:
            parts.append(f"{label} {pct:.0f}%")
    return " · ".join(parts)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8") or "{}")
    except ValueError:
        data = {}
    if data.get("rate_limits"):
        try:
            save_limits(data["rate_limits"])
        except OSError:
            pass  # the status line must never fail because of the dashboard
    print(status_text(data))


if __name__ == "__main__":
    main()
