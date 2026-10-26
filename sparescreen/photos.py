"""Photos for the Photos screen, from a folder the user picks in the PC window.

The folder (and its subfolders) is looked at every SCAN_EVERY seconds, so photos added or
removed show up by themselves. The page gets the list once it changes (GET /photos) and
each photo by its id (GET /photo/<id>), paired devices only, like the album covers. Ids
come from the file's path, size and time, so the page never sees the PC's paths, and a
changed file gets a new id (and a fresh copy past the browser's cache).

Big camera photos are made screen-sized before they go to the phone, and turned the way
the camera meant (EXIF), when Pillow is installed (it is on Windows): old phones have
little memory and old browsers ignore EXIF. Without Pillow the file goes as it is.
HEIC (iPhone) isn't shown: old browsers can't open it.
"""

from __future__ import annotations

import collections
import hashlib
import io
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from .shapes import Json

TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
         ".gif": "image/gif"}
SCAN_EVERY = 30   # seconds
MAX_PHOTOS = 2000
MAX_SIDE = 1600   # pixels: enough for a phone screen, small enough for an old one
CACHE = 12        # resized photos kept in memory


def pick_folder() -> Optional[str]:
    """The system's own "choose a folder" dialog, on this PC. None when cancelled or when
    there's no dialog to use (the folder can still be typed in the PC window)."""
    if sys.platform == "win32":
        script = ("Add-Type -AssemblyName System.Windows.Forms;"
                  "$d = New-Object System.Windows.Forms.FolderBrowserDialog;"
                  "$d.Description = 'Folder with the photos for SpareScreen';"
                  "$owner = New-Object System.Windows.Forms.Form -Property @{TopMost = $true};"
                  "if ($d.ShowDialog($owner) -eq 'OK') { [Console]::Out.Write($d.SelectedPath) }")
        command = ["powershell", "-NoProfile", "-STA", "-Command", script]
    elif sys.platform == "darwin":
        command = ["osascript", "-e", 'POSIX path of (choose folder with prompt "Folder with the photos")']
    elif shutil.which("zenity"):
        command = ["zenity", "--file-selection", "--directory", "--title=Folder with the photos"]
    elif shutil.which("kdialog"):
        command = ["kdialog", "--getexistingdirectory", str(Path.home())]
    else:
        return None
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=600,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return None
    folder = result.stdout.strip()
    return folder if folder and os.path.isdir(folder) else None


def can_pick() -> bool:
    return sys.platform in ("win32", "darwin") or bool(shutil.which("zenity") or shutil.which("kdialog"))


class Photos:
    """Also a data source ("photos"): how many there are, and a version that changes with the list."""

    name = "photos"

    def __init__(self, folder: Callable[[], Optional[str]]) -> None:
        self.folder = folder  # the user's choice, read on every scan (it can change)
        self._paths: dict[str, Path] = {}  # id -> file
        self._order: list[str] = []
        self._version = ""
        self._error: Optional[str] = None
        self._scanned_at: float = 0
        self._scanned_folder: Optional[str] = None
        self._cache: collections.OrderedDict[str, tuple[bytes, str]] = collections.OrderedDict()
        self._lock = threading.Lock()

    def _scan(self) -> None:
        folder = self.folder()
        ids: list[str] = []
        paths: dict[str, Path] = {}
        error = None
        if folder:
            root = Path(folder)
            if not root.is_dir():
                error = "The photo folder isn't there any more."
            else:
                for dirpath, dirnames, filenames in os.walk(root):
                    dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
                    for name in sorted(filenames):
                        path = Path(dirpath) / name
                        if name.startswith(".") or path.suffix.lower() not in TYPES:
                            continue
                        try:
                            st = path.stat()
                        except OSError:
                            continue
                        key = f"{path.relative_to(root)}|{st.st_size}|{st.st_mtime_ns}"
                        photo_id = hashlib.sha1(key.encode("utf-8", "replace")).hexdigest()[:16]
                        ids.append(photo_id)
                        paths[photo_id] = path
                        if len(ids) >= MAX_PHOTOS:
                            break
                    if len(ids) >= MAX_PHOTOS:
                        break
        with self._lock:
            self._order, self._paths, self._error = ids, paths, error
            self._version = hashlib.sha1("".join(ids).encode()).hexdigest()[:12] if ids else ""
            self._scanned_folder = folder

    def _fresh(self) -> None:
        now = time.time()
        if now - self._scanned_at >= SCAN_EVERY or self.folder() != self._scanned_folder:
            self._scanned_at = now
            self._scan()

    def rescan(self) -> None:
        """Right away, e.g. after the user picked another folder."""
        self._scanned_at = 0
        self._fresh()

    def read(self) -> Json:
        self._fresh()
        with self._lock:
            return {"count": len(self._order), "version": self._version}

    def listing(self) -> Json:
        self._fresh()
        with self._lock:
            return {"photos": list(self._order), "version": self._version}

    def status(self) -> Json:
        """For the PC window."""
        self._fresh()
        with self._lock:
            return {"folder": self._scanned_folder, "count": len(self._order), "error": self._error}

    def image(self, photo_id: str) -> Optional[tuple[bytes, str]]:
        """(bytes, content type) of one photo, screen-sized when Pillow can do it."""
        with self._lock:
            path = self._paths.get(photo_id)
            cached = self._cache.get(photo_id)
            if cached:
                self._cache.move_to_end(photo_id)
                return cached
        if path is None:
            return None
        try:
            data = path.read_bytes()
        except OSError:
            return None
        kind = TYPES[path.suffix.lower()]
        if kind != "image/gif":  # a GIF may be animated: as it is
            data, kind = _screen_sized(data, kind)
        with self._lock:
            self._cache[photo_id] = (data, kind)
            while len(self._cache) > CACHE:
                self._cache.popitem(last=False)
        return data, kind


def _screen_sized(data: bytes, kind: str) -> tuple[bytes, str]:
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return data, kind
    try:
        with Image.open(io.BytesIO(data)) as image:
            image = ImageOps.exif_transpose(image) or image
            image.thumbnail((MAX_SIDE, MAX_SIDE))
            out = io.BytesIO()
            if image.mode in ("RGBA", "LA", "P"):
                image.save(out, "PNG", optimize=True)
                return out.getvalue(), "image/png"
            image.convert("RGB").save(out, "JPEG", quality=85)
            return out.getvalue(), "image/jpeg"
    except Exception:  # a file Pillow can't read: send it as it is, the browser may manage
        return data, kind
