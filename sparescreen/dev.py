"""Dev mode (sparescreen --dev).

- A .py changed: the agent restarts by itself.
- Something in web/ changed (or the agent restarted): the page on the phone reloads by itself.

It works with two processes: this supervisor, which watches the files, and the
real agent as a child process. The page notices the change through the "version"
sent along with the data (`dev` field).
"""

import os
import subprocess
import sys
import time
from pathlib import Path

PACKAGE = Path(__file__).parent
CHILD_ENV = "SPARESCREEN_DEV_CHILD"
RESTART_ENV = "SPARESCREEN_DEV_RESTART"


def _python_mtimes():
    return {p: p.stat().st_mtime for p in PACKAGE.rglob("*.py")}


class DevSource:
    """Code version: changes when the agent restarts or a page file changes."""

    name = "dev"

    def __init__(self):
        self.started = time.time()

    def read(self):
        web = max((p.stat().st_mtime for p in (PACKAGE / "web").iterdir()), default=0)
        return f"{self.started:.0f}-{web:.3f}"


def is_child():
    return bool(os.environ.get(CHILD_ENV))


def is_restart():
    return bool(os.environ.get(RESTART_ENV))


def supervise(argv):
    """Runs the agent in a child process and restarts it when a .py changes."""
    env = dict(os.environ, **{CHILD_ENV: "1"})
    snapshot = _python_mtimes()
    child = None
    print("[dev] dev mode: the agent restarts when a .py file changes and the page reloads by itself.", flush=True)
    try:
        while True:
            if child is None:
                child = subprocess.Popen([sys.executable, "-m", "sparescreen", *argv], env=env)
                env[RESTART_ENV] = "1"  # on later restarts, do not reopen the page on the phone
            time.sleep(1)
            current = _python_mtimes()
            if current != snapshot:
                snapshot = current
                print("[dev] Python code changed, restarting the agent...", flush=True)
                if child.poll() is None:
                    child.terminate()
                    child.wait(timeout=10)
                child = None
            elif child.poll() is not None and not getattr(child, "_reported", False):
                # Probably an error in the code: wait for the next change to try again.
                child._reported = True
                print("[dev] the agent stopped. Fix the error above and save; it will come back by itself.", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
