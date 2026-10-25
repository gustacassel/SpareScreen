"""Claude Code status line that passes the usage limits on to the dashboard.

Configured in ~/.claude/settings.json ("statusLine"). Claude Code runs this
command on every update and sends the session data as JSON on stdin; the
`rate_limits` field (5-hour and weekly windows) only exists on Pro/Max plans.
We save that field to a file that the dashboard agent reads.

Keeping an existing status line: put the user's own command after `--`, e.g.
`sparescreen-statusline -- bash ~/.claude/my-status.sh`. Claude Code's shell
splits and expands it, and we run it as an argument list (no extra shell, no
quoting rules that differ between Windows and Unix). A single quoted argument
that isn't an executable, e.g. `-- "my-status | head -1"`, is run by the
system shell so pipes keep working. Without `--`, the environment variable
SPARESCREEN_STATUSLINE_CMD (always a shell command line) is used instead.
The wrapped command gets the same stdin bytes; its stdout and exit code are
passed through unchanged. If it can't start, times out, or fails without
printing anything, we print our own text instead, so the line never goes blank.
"""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

LIMITS_FILE = Path.home() / ".sparescreen" / "claude-limits.json"
WRAP_ENV = "SPARESCREEN_STATUSLINE_CMD"
WRAP_TIMEOUT = 5  # seconds; Claude Code refreshes often and a stuck script must not hang it
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


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


def wrapped_command(argv):
    """The user's own status line as (command, use_shell), or None."""
    if "--" in argv:
        rest = argv[argv.index("--") + 1:]
        if len(rest) > 1:
            return rest, False
        if rest and rest[0].strip():
            # One argument: either a plain executable or a whole quoted command line.
            return (rest, False) if shutil.which(rest[0]) else (rest[0], True)
    command = os.environ.get(WRAP_ENV, "").strip()
    return (command, True) if command else None


def run_wrapped(command, shell, raw):
    """Run the user's status line with our stdin; (stdout bytes, exit code) or None."""
    env = dict(os.environ)
    env.pop(WRAP_ENV, None)  # if it calls sparescreen-statusline again, it must not wrap itself forever
    if not shell:
        # Windows only launches .cmd/.bat (npx, ...) and "dir/x.exe" paths when given the full path.
        found = shutil.which(command[0])
        command = [os.path.abspath(found) if found else command[0]] + list(command[1:])
    try:
        proc = subprocess.Popen(command, shell=shell, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                env=env, creationflags=_NO_WINDOW)
    except (OSError, ValueError):
        return None
    try:
        out, _ = proc.communicate(raw, timeout=WRAP_TIMEOUT)
    except subprocess.TimeoutExpired:
        # No second communicate(): a grandchild still holding the pipe would block us again.
        proc.kill()
        return None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return out, proc.returncode


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    raw = sys.stdin.buffer.read()  # kept as bytes so a wrapped command gets exactly the same input
    try:
        data = json.loads(raw.decode("utf-8") or "{}")
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    if data.get("rate_limits"):
        try:
            save_limits(data["rate_limits"])
        except (OSError, TypeError, ValueError):
            pass  # the status line must never fail because of the dashboard
    wrapped = wrapped_command(sys.argv[1:] if argv is None else argv)
    if wrapped:
        result = run_wrapped(wrapped[0], wrapped[1], raw)
        if result and (result[0] or result[1] == 0):
            sys.stdout.flush()
            sys.stdout.buffer.write(result[0])  # bytes as-is: multi-line, any encoding, colors
            sys.stdout.buffer.flush()
            return result[1]
    print(status_text(data))


if __name__ == "__main__":
    sys.exit(main())
