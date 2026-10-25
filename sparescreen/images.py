"""Images the page shows (album covers, game art, app icons), kept in memory.

Sources put an image here and send its URL ("art/<key>?v=<version>") with their data;
the server answers /art/<key> with the bytes. The version changes when the image
does, so the phone's browser refreshes it without re-downloading every second.
"""

from __future__ import annotations

import hashlib
import mimetypes
import os
import threading
from pathlib import Path

MAX_BYTES = 4 * 1024 * 1024  # covers and icons are small; ignore anything huge
_lock = threading.Lock()
_store: dict[str, tuple[bytes, str, str]] = {}  # key -> (bytes, content type, version)


def put(key: str, data: bytes | None, content_type: str) -> str | None:
    """Store an image and return its URL for the page (None if there's nothing usable)."""
    if not data or len(data) > MAX_BYTES:
        return None
    version = hashlib.sha1(data).hexdigest()[:12]
    with _lock:
        current = _store.get(key)
        if not current or current[2] != version:
            _store[key] = (data, content_type, version)
    return f"art/{key}?v={version}"


def put_file(key: str, path: str | os.PathLike[str]) -> str | None:
    """Same as put(), reading the image from a file (e.g. Steam's cached game art)."""
    try:
        path = Path(path)
        if not path.is_file() or path.stat().st_size > MAX_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    return put(key, data, mimetypes.guess_type(path.name)[0] or "image/jpeg")


def get(key: str) -> tuple[bytes, str] | None:
    """(bytes, content type) or None."""
    with _lock:
        item = _store.get(key)
    return (item[0], item[1]) if item else None
