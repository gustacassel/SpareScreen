"""Updates: notices when a newer SpareScreen is released and, for the packaged executable,
replaces itself with it (the PC window's "Update" button).

- Checking: a minute after starting and then every 6 hours, one request to GitHub's public
  API for the latest release. Nothing about the user or the PC is sent. The "update_check"
  setting turns it off.
- Installing (packaged executable only): this system's file from the release is downloaded
  next to the running one and checked against the release's SHA256SUMS, then run once with
  --version to be sure it starts here. Then the swap: the running file is renamed to
  <name>.old (Windows lets a running .exe be renamed, not overwritten) and the new one takes
  its place, at the same path, so autostart keeps working. SpareScreen then quits and starts
  again from that path (relaunch()); the new version deletes the .old file once it's up.
- From a git clone (or pip): only the notice; the code there is never touched.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

from . import __version__
from .dev import RESTART_ENV
from .shapes import Json

if TYPE_CHECKING:
    from .config import ConfigStore

REPO = "gustacassel/SpareScreen"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{REPO}/releases/latest"
# The executable each release carries per system (see .github/workflows/release.yml).
ASSETS = {"win32": "sparescreen-windows-x64.exe", "linux": "sparescreen-linux-x64",
          "darwin": "sparescreen-macos-arm64"}
SUMS = "SHA256SUMS"
FIRST_CHECK = 60  # seconds after starting: not while everything else is starting up
CHECK_EVERY = 6 * 3600
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def parse_version(text: object) -> tuple[int, ...]:
    """'v0.11.0' -> (0, 11, 0); anything that isn't a plain version -> ()."""
    match = re.match(r"v?(\d+(?:\.\d+)*)$", text.strip()) if isinstance(text, str) else None
    return tuple(int(part) for part in match.group(1).split(".")) if match else ()


def is_newer(latest: object, current: str) -> bool:
    found = parse_version(latest)
    return bool(found) and found > parse_version(current)


def parse_sums(text: str) -> dict[str, str]:
    """sha256sum's output ("<hex>  <name>", "*<name>" in binary mode) -> {name: hex}."""
    sums = {}
    for line in text.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            sums[parts[1].lstrip("*").strip()] = parts[0].lower()
    return sums


def _get(url: str, timeout: float = 15) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": f"SpareScreen/{__version__}",
                                                   "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        data: bytes = resp.read()
        return data


def _from_clone() -> bool:
    return (Path(__file__).resolve().parent.parent / ".git").exists()


class Updater:
    """Also a data source ("update"): the page reloads itself when the version changes."""

    name = "update"

    def __init__(self, config: Optional[ConfigStore] = None, current: str = __version__,
                 frozen: Optional[bool] = None, executable: Optional[str] = None,
                 platform: Optional[str] = None, latest_url: str = LATEST_URL) -> None:
        self.config = config
        self.current = current
        self.frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
        self.executable = Path(executable or sys.executable)
        self.asset = ASSETS.get(platform or sys.platform)
        self.latest_url = latest_url
        self.latest: Optional[Json] = None  # {"version", "url", "assets": {name: download url}}
        self.checked_at: Optional[float] = None
        self.error: Optional[str] = None
        self.status = "idle"  # idle, checking, downloading, restarting or failed
        self.progress: Optional[int] = None  # % downloaded
        self.relaunch_wanted = False  # set once the new file is in place: see relaunch()
        self.quit: Optional[Callable[[], None]] = None  # stops SpareScreen (set by cli)
        self._lock = threading.Lock()

    # ---- checking ---------------------------------------------------------------

    def enabled(self) -> bool:
        return bool(self.config.read().get("update_check", True)) if self.config else True

    def check(self) -> None:
        """Asks GitHub for the latest release. A failure is kept as `error`, never raised."""
        with self._lock:
            if self.status in ("downloading", "restarting"):
                return
            self.status = "checking"
        try:
            release = json.loads(_get(self.latest_url))
            assets = {a["name"]: a["browser_download_url"] for a in release.get("assets") or []
                      if isinstance(a, dict) and isinstance(a.get("name"), str)
                      and isinstance(a.get("browser_download_url"), str)}
            version = str(release.get("tag_name") or "").lstrip("v")
            if not parse_version(version):
                raise ValueError(f"unexpected release name {release.get('tag_name')!r}")
            self.latest = {"version": version, "url": str(release.get("html_url") or RELEASES_URL),
                           "assets": assets}
            self.error = None
        except (OSError, ValueError, AttributeError, TypeError) as exc:
            self.error = f"Couldn't check for updates: {exc}"
        self.checked_at = time.time()
        with self._lock:
            if self.status == "checking":
                self.status = "idle"

    def check_now(self) -> None:
        """The PC window's "Check now": works even with the automatic check off."""
        threading.Thread(target=self.check, name="update-check-now", daemon=True).start()

    def start(self) -> None:
        def loop() -> None:
            time.sleep(FIRST_CHECK)
            while True:
                due = self.checked_at is None or time.time() - self.checked_at >= CHECK_EVERY
                if self.enabled() and due:
                    self.check()
                time.sleep(60)  # a check turned back on happens within a minute

        threading.Thread(target=loop, name="update-check", daemon=True).start()

    def available(self) -> Optional[str]:
        """The newer version's number, if there is one."""
        latest = self.latest
        return latest["version"] if latest and is_newer(latest["version"], self.current) else None

    def can_install(self) -> bool:
        latest = self.latest
        return (self.frozen and bool(self.available()) and latest is not None
                and self.asset in latest["assets"] and SUMS in latest["assets"])

    def how(self) -> str:
        """How to get the new version when the button can't do it."""
        if not self.frozen:
            return ("Run git pull in the SpareScreen folder, then restart it." if _from_clone()
                    else "Download it from the release page.")
        latest = self.latest or {"assets": {}}
        if self.asset not in latest["assets"]:
            return "That release has no file for this system: see the release page."
        if SUMS not in latest["assets"]:
            return "That release has no checksums to verify the download: get it from the release page."
        return ""

    def read(self) -> Json:
        return {"version": self.current, "latest": self.available()}

    def state(self) -> Json:
        """For the PC window."""
        latest = self.latest
        return {"current": self.current, "latest": self.available(), "url": latest["url"] if latest else RELEASES_URL,
                "enabled": self.enabled(), "checked_at": self.checked_at, "error": self.error,
                "status": self.status, "progress": self.progress, "can_install": self.can_install(),
                "how": "" if self.can_install() else self.how()}

    # ---- installing -------------------------------------------------------------

    @property
    def new_file(self) -> Path:
        return self.executable.with_name(self.executable.name + ".new")

    @property
    def old_file(self) -> Path:
        return self.executable.with_name(self.executable.name + ".old")

    def install(self) -> None:
        """Downloads, checks and swaps in the new version on a thread, then quits to restart."""
        with self._lock:
            if not self.can_install() or self.status in ("downloading", "restarting"):
                return
            self.status, self.progress, self.error = "downloading", 0, None
        threading.Thread(target=self._install, name="update-install", daemon=True).start()

    def _install(self) -> None:
        try:
            self._download_and_swap()
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            self.error = str(exc) if isinstance(exc, ValueError) else f"The update failed: {exc}"
            self.status = "failed"
            try:
                self.new_file.unlink()
            except OSError:
                pass
            return
        self.status = "restarting"
        self.relaunch_wanted = True
        if self.quit:
            self.quit()

    def _download_and_swap(self) -> None:
        latest = self.latest
        assert latest is not None and self.asset is not None  # can_install() checked both
        expected = parse_sums(_get(latest["assets"][SUMS]).decode("utf-8", "replace")).get(self.asset)
        if not expected:
            raise ValueError(f"The release's checksums don't list {self.asset}, so it wasn't installed.")
        self._download(latest["assets"][self.asset], expected)
        if sys.platform != "win32":
            os.chmod(self.new_file, self.executable.stat().st_mode | 0o111)
        # A file that can't run here (another architecture, a too old system) stops here.
        result = subprocess.run([str(self.new_file), "--version"], capture_output=True, text=True, timeout=120,
                                env=dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1"), creationflags=_NO_WINDOW)
        if latest["version"] not in result.stdout:
            raise ValueError("The new version didn't start on this PC, so it wasn't installed.")
        os.replace(self.executable, self.old_file)
        try:
            os.replace(self.new_file, self.executable)
        except OSError:
            os.replace(self.old_file, self.executable)  # put the running one back
            raise

    def _download(self, url: str, expected: str) -> None:
        digest = hashlib.sha256()
        request = urllib.request.Request(url, headers={"User-Agent": f"SpareScreen/{__version__}"})
        with urllib.request.urlopen(request, timeout=60) as resp, open(self.new_file, "wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                self.progress = min(99, done * 100 // total) if total else None
        if digest.hexdigest() != expected:
            raise ValueError("The download didn't match the release's checksum, so it was discarded.")
        self.progress = 100

    def clean_up(self) -> None:
        """Deletes the previous version's file left by an update. On Windows it can stay
        locked for a few seconds while the old process exits, so this keeps trying a while."""
        if not self.frozen or not self.old_file.exists():
            return

        def remove() -> None:
            for _ in range(30):
                try:
                    self.old_file.unlink()
                    return
                except FileNotFoundError:
                    return
                except OSError:
                    time.sleep(2)

        threading.Thread(target=remove, name="update-clean-up", daemon=True).start()


def relaunch(extra_env: Optional[dict[str, str]] = None) -> None:
    """Starts the (new) executable at this same path with the same options. Called once
    SpareScreen has shut down, so the new one finds the port free."""
    exe = sys.executable
    # PYINSTALLER_RESET_ENVIRONMENT: the new one unpacks its own files, not this one's;
    # RESTART_ENV: the phone already has the page open, don't open it again.
    env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1", **{RESTART_ENV: "1"}, **(extra_env or {}))
    args = sys.argv[1:]
    if sys.platform == "win32":
        # A windowless process in the tray, like the double-clicked .exe ends up as.
        if "--background" not in args:
            args = args + ["--background"]
        flags = _NO_WINDOW | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen([exe] + args, env=env, close_fds=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
    else:
        os.execve(exe, [exe] + args, env)  # same process, same terminal if there is one
