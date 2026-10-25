"""Game FPS on Windows, from Intel's PresentMon (free, MIT).

PresentMon reads, through Windows' event tracing (ETW), when each frame of a game is
handed to the screen, for any graphics API. SpareScreen starts it only while a game
runs, pointed at the game's process, and turns its per-frame output into FPS, 1% low
and frame time.

Setting it up is the user's choice, from the PC window ("Enable"):
- the PresentMon console app is downloaded once from its GitHub release, pinned to one
  version and checked against its SHA-256, into ~/.sparescreen/tools;
- ETW tracing needs admin rights or membership in Windows' "Performance Log Users"
  group. Joining the group once (Windows asks for admin rights, then a sign-out and
  back in) lets SpareScreen run PresentMon without admin prompts while you play.

Other systems: no FPS for now (Linux could read MangoHud's logs later).
"""

import collections
import csv
import hashlib
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

VERSION = "2.6.0"
URL = f"https://github.com/GameTechDev/PresentMon/releases/download/v{VERSION}/PresentMon-{VERSION}-x64.exe"
SHA256 = "b2a706bc6ad475749e3b7e3409263aa1e6906d45bdcf993f6dbc0f660188f1af"
TOOLS = Path.home() / ".sparescreen" / "tools"
EXE = TOOLS / f"PresentMon-{VERSION}-x64.exe"
GROUP_SID = "S-1-5-32-559"  # "Performance Log Users", whatever the Windows language
SESSION = "SpareScreen"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ---- setup -------------------------------------------------------------------

def find_presentmon():
    """Our pinned download, or a PresentMon the user already has on the PATH."""
    if EXE.is_file():
        return str(EXE)
    return shutil.which("PresentMon") or shutil.which("PresentMon-x64")


def download():
    """Downloads the pinned PresentMon and checks its hash. Returns an error message or None."""
    TOOLS.mkdir(parents=True, exist_ok=True)
    tmp = EXE.with_suffix(".part")
    try:
        with urllib.request.urlopen(URL, timeout=60) as resp, open(tmp, "wb") as out:
            shutil.copyfileobj(resp, out)
        digest = hashlib.sha256(tmp.read_bytes()).hexdigest()
        if digest != SHA256:
            tmp.unlink()
            return "The download didn't match PresentMon's published checksum, so it was discarded."
        os.replace(tmp, EXE)
    except OSError as exc:
        return f"Couldn't download PresentMon: {exc}"
    return None


def allowed():
    """True when this process may start ETW sessions: in the group (after signing back in) or elevated."""
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.windll.advapi32
    sid = ctypes.c_void_p()
    if not advapi32.ConvertStringSidToSidW(GROUP_SID, ctypes.byref(sid)):
        return False
    try:
        member = wintypes.BOOL()
        if advapi32.CheckTokenMembership(None, sid, ctypes.byref(member)) and member.value:
            return True
    finally:
        ctypes.windll.kernel32.LocalFree(sid)
    return bool(ctypes.windll.shell32.IsUserAnAdmin())


REQUESTED = TOOLS / "fps-permission-requested"  # joined the group; waiting for a new sign-in


def requested():
    return REQUESTED.is_file()


def join_group():
    """Asks Windows (admin prompt) to add this user to "Performance Log Users".
    Returns an error message or None; it takes effect after signing out and back in."""
    import ctypes

    user = f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}".lstrip("\\")
    command = f"Add-LocalGroupMember -SID '{GROUP_SID}' -Member '{user}' -ErrorAction SilentlyContinue"
    # ShellExecute with "runas" is how a program asks Windows for admin rights (the UAC prompt).
    result = ctypes.windll.shell32.ShellExecuteW(None, "runas", "powershell.exe",
                                                 f'-NoProfile -WindowStyle Hidden -Command "{command}"', None, 0)
    if result <= 32:
        return "Windows asked for permission and it was refused." if result == 5 else f"Couldn't ask Windows ({result})."
    TOOLS.mkdir(parents=True, exist_ok=True)
    REQUESTED.write_text("", encoding="utf-8")
    return None


def enable():
    """The PC window's "Enable": download PresentMon if needed, then ask for the permission.
    Returns the message to show."""
    if not find_presentmon():
        error = download()
        if error:
            return error
    if allowed():
        return "FPS is ready: it shows on the game screen while you play."
    error = join_group()
    if error:
        return error
    return "Almost there: sign out of Windows and back in to finish turning on FPS."


# ---- measuring -------------------------------------------------------------

def frame_column(header):
    """Index of the frame-to-frame time in PresentMon's CSV header (named differently over versions)."""
    for name in ("MsBetweenPresents", "FrameTime", "MsBetweenAppStart"):
        if name in header:
            return header.index(name)
    return None


class FrameStats:
    """Frame times of the last seconds -> FPS, 1% low and average frame time."""

    def __init__(self, window=10.0, now=time.monotonic):
        self.window = window
        self.now = now
        self._frames = collections.deque()  # (arrival time, frame time in ms)
        self._lock = threading.Lock()

    def add(self, ms):
        if not 0 < ms < 5000:  # pauses and loading screens aren't frames worth counting
            return
        with self._lock:
            now = self.now()
            self._frames.append((now, ms))
            while self._frames and now - self._frames[0][0] > self.window:
                self._frames.popleft()

    def summary(self):
        with self._lock:
            now = self.now()
            recent = [ms for at, ms in self._frames if now - at <= 2.0]  # what's on screen now
            window = [ms for at, ms in self._frames if now - at <= self.window]
        if not recent:
            return None
        frametime = sum(recent) / len(recent)
        worst = sorted(window)[-max(1, len(window) // 100):]  # the slowest 1% of frames
        return {"fps": round(1000 / frametime), "low1": round(1000 / (sum(worst) / len(worst))),
                "frametime": round(frametime, 1)}


class FpsSource:
    """FPS of the game the activity source found; starts and stops PresentMon with it."""

    name = "fps"

    def __init__(self, activity):
        self.activity = activity
        self._proc = None
        self._pid = None
        self._stats = None
        self._error = None

    def read(self):
        if sys.platform != "win32":
            return {"available": False}
        game = (self.activity.read() or {}).get("game")
        pid = game.get("pid") if game else None
        if pid != self._pid:
            self._stop()
            if pid:
                self._start(pid)
        if not pid:
            return {"available": True, "playing": False}
        summary = self._stats.summary() if self._stats else None
        return dict({"available": True, "playing": True, "error": self._error}, **(summary or {}))

    def _start(self, pid):
        self._pid, self._error = pid, None
        exe = find_presentmon()
        if not exe:
            self._error = "setup"  # the PC window offers to set it up
            return
        if not allowed():
            self._error = "permission"
            return
        self._stats = FrameStats()
        try:
            self._proc = subprocess.Popen(
                [exe, "--process_id", str(pid), "--output_stdout", "--no_console_stats",
                 "--session_name", SESSION, "--stop_existing_session",
                 "--no_track_gpu", "--no_track_input", "--no_track_display"],  # only what FPS needs
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                text=True, creationflags=_NO_WINDOW)
        except OSError:
            self._error = "failed"
            return
        threading.Thread(target=self._read_frames, args=(self._proc, self._stats), daemon=True).start()

    def _read_frames(self, proc, stats):
        column = None
        for row in csv.reader(proc.stdout):
            if column is None:
                column = frame_column(row)
                continue
            try:
                stats.add(float(row[column]))
            except (IndexError, ValueError):
                pass  # "NA" or a short line
        if proc.wait() != 0 and proc is self._proc:
            err = proc.stderr.read() if proc.stderr else ""
            self._error = "permission" if "access denied" in err else "failed"

    def _stop(self):
        proc, self._proc, self._stats, self._pid = self._proc, None, None, None
        if proc and proc.poll() is None:
            proc.terminate()
            # A killed PresentMon leaves its trace session behind: close it properly.
            try:
                subprocess.run([proc.args[0], "--terminate_existing_session", "--session_name", SESSION],
                               capture_output=True, timeout=10, creationflags=_NO_WINDOW)
            except (OSError, subprocess.SubprocessError):
                pass
