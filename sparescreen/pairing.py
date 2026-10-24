"""Pairing: only devices that typed the pairing code can see the data.

The agent shows a 6-digit code. A new device sends it once and gets a random
token back in a long-lived cookie; from then on the cookie is enough. Only a
hash of each token is stored on the PC (~/.sparescreen/devices.json).

Requests from this machine are always trusted: the PC's own browser and phones
on USB (adb reverse makes them connect through 127.0.0.1).
"""

import hashlib
import json
import os
import secrets
import threading
import time
from http.cookies import SimpleCookie
from pathlib import Path

DEVICES_FILE = Path.home() / ".sparescreen" / "devices.json"
COOKIE = "sparescreen_token"
LOCAL_ADDRESSES = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}
MAX_FAILURES = 5     # wrong codes in a row before a short lockout
LOCKOUT = 60         # seconds


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


class Pairing:
    def __init__(self, path=DEVICES_FILE, trust_localhost=True):
        self.path = path
        self.trust_localhost = trust_localhost
        self.code = f"{secrets.randbelow(10 ** 6):06d}"
        self._lock = threading.Lock()
        self._failures = 0
        self._locked_until = 0
        try:
            self._devices = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._devices = []

    def is_trusted(self, address, cookie_header):
        if self.trust_localhost and address in LOCAL_ADDRESSES:
            return True
        token = self._token(cookie_header)
        if not token:
            return False
        digest = _hash(token)
        with self._lock:
            return any(secrets.compare_digest(d.get("hash", ""), digest) for d in self._devices)

    def pair(self, code, device=""):
        """Returns (token, None) on success or (None, error), where error is
        ("wrong", attempts_left) or ("locked", seconds_left)."""
        with self._lock:
            now = time.time()
            if now < self._locked_until:
                return None, ("locked", int(self._locked_until - now) + 1)
            if not secrets.compare_digest(str(code).strip(), self.code):
                self._failures += 1
                if self._failures >= MAX_FAILURES:
                    self._failures = 0
                    self._locked_until = now + LOCKOUT
                    return None, ("locked", LOCKOUT)
                return None, ("wrong", MAX_FAILURES - self._failures)
            self._failures = 0
            token = secrets.token_urlsafe(32)
            self._devices.append({"hash": _hash(token), "added": int(now), "device": device[:120]})
            self._save()
            return token, None

    def reset(self):
        """Forget every paired device."""
        with self._lock:
            self._devices = []
            self._save()

    def cookie_header(self, token):
        ten_years = 10 * 365 * 24 * 3600
        return f"{COOKIE}={token}; Max-Age={ten_years}; Path=/; HttpOnly; SameSite=Strict"

    def _token(self, cookie_header):
        if not cookie_header:
            return None
        try:
            morsel = SimpleCookie(cookie_header).get(COOKIE)
        except Exception:  # malformed cookie header
            return None
        return morsel.value if morsel else None

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._devices, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)
