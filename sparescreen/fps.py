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

# PresentMon writes frame rows only to a file (to a pipe it writes the header and stops), and
# writes it as it goes, so SpareScreen reads the file while it grows. --no_track_display would
# save a little more work, but with it PresentMon writes nothing at all.
CAPTURE_OPTIONS = ["--no_console_stats", "--no_track_gpu", "--no_track_input"]


def capture_command(exe, pid, path, seconds, session):
    return [exe, "--process_id", str(pid), "--output_file", str(path), "--timed", str(seconds),
            "--terminate_after_timed", "--session_name", session, "--stop_existing_session"] + CAPTURE_OPTIONS


def _remove(path):
    try:
        path.unlink()
    except OSError:
        pass


def frame_column(header):
    """Index of the frame-to-frame time in PresentMon's CSV header (named differently over versions)."""
    for name in ("MsBetweenPresents", "FrameTime", "MsBetweenAppStart"):
        if name in header:
            return header.index(name)
    return None


class FrameStats:
    """Frame times of the last seconds -> FPS, 1% low and average frame time."""

    RECENT = 4.0  # seconds counted as "now" (frames arrive in ~2 s batches)

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
            recent = [ms for at, ms in self._frames if now - at <= self.RECENT]  # what's on screen now
            window = [ms for at, ms in self._frames if now - at <= self.window]
        if not recent:
            return None
        frametime = sum(recent) / len(recent)
        worst = sorted(window)[-max(1, len(window) // 100):]  # the slowest 1% of frames
        return {"fps": round(1000 / frametime), "low1": round(1000 / (sum(worst) / len(worst))),
                "frametime": round(frametime, 1)}


class AutoDetect:
    """Is the full-screen app in front a game? PresentMon watches it for a few seconds:
    a game keeps drawing frames all the time, a full-screen document or menu doesn't.

    Only where FPS is set up (PresentMon and its permission), and only for the app in
    front, so PresentMon isn't running when nobody plays. Answers are remembered per
    program: a game for the rest of the session, a non-game for a few minutes.
    """

    SECONDS = 4
    MIN_FPS = 20
    RECHECK = 300  # seconds before asking again about a program that wasn't a game

    def __init__(self):
        self._verdicts = {}  # exe -> (is it a game, when)
        self._busy = False
        self._lock = threading.Lock()

    @staticmethod
    def ready():
        return sys.platform == "win32" and bool(find_presentmon()) and allowed()

    def is_game(self, pid, exe):
        """True once confirmed; False while unknown (a check runs in the background)."""
        with self._lock:
            verdict = self._verdicts.get(exe)
            if verdict and (verdict[0] or time.time() - verdict[1] < self.RECHECK):
                return verdict[0]
            if self._busy or not self.ready():
                return False
            self._busy = True
        threading.Thread(target=self._check, args=(pid, exe), daemon=True).start()
        return False

    def _check(self, pid, exe):
        path = TOOLS / f"check-{os.getpid()}.csv"
        try:
            TOOLS.mkdir(parents=True, exist_ok=True)
            _remove(path)
            subprocess.run(capture_command(find_presentmon(), pid, path, self.SECONDS, SESSION + "Check"),
                           capture_output=True, timeout=self.SECONDS + 15, creationflags=_NO_WINDOW)
            game = path.is_file() and self.looks_like_a_game(path.read_text(encoding="utf-8-sig", errors="replace"))
        except (OSError, subprocess.SubprocessError):
            game = False
        finally:
            _remove(path)
        with self._lock:
            self._verdicts[exe] = (game, time.time())
            self._busy = False

    @classmethod
    def looks_like_a_game(cls, output):
        times = frame_times(output)
        # Steady drawing: enough frames over the whole check, at a game-like rate.
        return len(times) >= cls.MIN_FPS * cls.SECONDS * 0.8 and 1000 / (sum(times) / len(times)) >= cls.MIN_FPS


class FpsSource:
    """FPS of the game the activity source found; starts and stops PresentMon with it."""

    name = "fps"

    STRETCH = 2  # seconds per recording; FPS updates this often

    def __init__(self, activity):
        self.activity = activity
        self._proc = None
        self._pid = None
        self._stats = None
        self._error = None
        self._stopped = None  # threading.Event of the current capture
        for left in list(TOOLS.glob("frames-*.csv")) + list(TOOLS.glob("check-*.csv")):
            _remove(left)  # from a run that was closed mid-recording

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
        self._stopped = threading.Event()
        threading.Thread(target=self._capture, args=(exe, pid, self._stats, self._stopped), daemon=True).start()

    def _capture(self, exe, pid, stats, stopped):
        # PresentMon keeps its file locked while writing, so it records short stretches
        # back to back and each one is read when it ends.
        path = TOOLS / f"frames-{os.getpid()}.csv"
        TOOLS.mkdir(parents=True, exist_ok=True)
        while not stopped.is_set():
            _remove(path)
            try:
                proc = subprocess.Popen(capture_command(exe, pid, path, self.STRETCH, SESSION),
                                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.PIPE, creationflags=_NO_WINDOW)
            except OSError:
                self._error = "failed"
                break
            self._proc = proc
            _, err = proc.communicate()
            if stopped.is_set():
                break
            if proc.returncode != 0:
                text = err.decode("utf-16", "replace") if b"\x00" in err else err.decode("utf-8", "replace")
                self._error = "permission" if "access denied" in text else "failed"
                break
            try:
                read_frames(path.read_text(encoding="utf-8-sig", errors="replace"), stats)
            except OSError:
                pass  # no frames this time (game paused, minimized...)
        _remove(path)

    def _stop(self):
        proc, self._proc, self._stats, self._pid = self._proc, None, None, None
        if self._stopped:
            self._stopped.set()
        if proc and proc.poll() is None:
            proc.terminate()
            # A killed PresentMon leaves its trace session behind: close it properly.
            try:
                subprocess.run([proc.args[0], "--terminate_existing_session", "--session_name", SESSION],
                               capture_output=True, timeout=10, creationflags=_NO_WINDOW)
            except (OSError, subprocess.SubprocessError):
                pass


def frame_times(text):
    """Frame-to-frame times (ms) in one of PresentMon's CSV files."""
    rows = list(csv.reader(text.splitlines()))
    column = frame_column(rows[0]) if rows else None
    times = []
    for row in rows[1:] if column is not None else []:
        try:
            times.append(float(row[column]))
        except (IndexError, ValueError):
            pass  # "NA" or a short line
    return times


def read_frames(text, stats):
    for ms in frame_times(text):
        stats.add(ms)
