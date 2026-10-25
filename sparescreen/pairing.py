"""Pairing: only devices that typed the pairing code can see the data.

The agent shows a 6-digit code. A new device sends it once and gets a random
token back in a long-lived cookie; from then on the cookie is enough. Only a
hash of each token is stored on the PC (~/.sparescreen/devices.json).

Requests from this machine are always trusted: the PC's own browser and phones
on USB (adb reverse makes them connect through 127.0.0.1).

One paired device at a time: pairing a new one forgets the previous one (the PC
window shows the code and who is asking for it). USB and the PC itself don't count.
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
WAITING_FOR = 120    # seconds a device that asked to pair shows up as "waiting"
HANDOFF_FOR = 60     # seconds a code to move a device to another address of the PC lasts


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


class Pairing:
    def __init__(self, path=DEVICES_FILE, trust_localhost=True, single=True):
        self.path = path
        self.trust_localhost = trust_localhost
        self.single = single
        self.code = f"{secrets.randbelow(10 ** 6):06d}"
        self._lock = threading.Lock()
        self._failures = 0
        self._locked_until = 0
        self._waiting = None  # the last device that asked to pair: {"address", "device", "at"}
        self._handoffs = {}   # one-time code -> (device hash, valid until)
        try:
            self._devices = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._devices = []

    def is_trusted(self, address, cookie_header):
        if self.trust_localhost and address in LOCAL_ADDRESSES:
            return True
        return self.paired_hash(cookie_header) is not None

    def paired_hash(self, cookie_header):
        """Hash of the cookie's token if it belongs to a paired device, else None."""
        token = self._token(cookie_header)
        if not token:
            return None
        digest = _hash(token)
        return digest if self.knows(digest) else None

    def knows(self, digest):
        with self._lock:
            return any(secrets.compare_digest(d.get("hash", ""), digest) for d in self._devices)

    def note_waiting(self, address, device):
        """A device that isn't paired opened the page: the PC window shows it with the code."""
        with self._lock:
            self._waiting = {"address": address, "device": device[:120], "at": time.time()}

    def waiting(self):
        with self._lock:
            if self._waiting and time.time() - self._waiting["at"] < WAITING_FOR:
                return dict(self._waiting)
            return None

    def devices(self):
        """Paired devices, without their hashes: [{"device", "address", "added"}]."""
        with self._lock:
            return [{"device": d.get("device", ""), "address": d.get("address"), "added": d.get("added")}
                    for d in self._devices]

    def pair(self, code, device="", address=None):
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
            if self.single:
                self._devices = []  # the new device replaces the previous one
            self._devices.append({"hash": _hash(token), "added": int(now), "device": device[:120],
                                  "address": address})
            self._waiting = None
            self._save()
            return token, None

    def handoff(self, digest):
        """A one-time code that moves a paired device to another address of this PC (the
        browser keeps the cookie per address, so it would have to pair again)."""
        code = secrets.token_urlsafe(24)
        with self._lock:
            now = time.time()
            self._handoffs = {c: h for c, h in self._handoffs.items() if h[1] > now}
            self._handoffs[code] = (digest, now + HANDOFF_FOR)
        return code

    def redeem(self, code, address=None):
        """The new token for the device the code was made for, or None. Single use."""
        with self._lock:
            digest, until = self._handoffs.pop(str(code), (None, 0))
            if not digest or time.time() > until:
                return None
            for device in self._devices:
                if secrets.compare_digest(device.get("hash", ""), digest):
                    token = secrets.token_urlsafe(32)
                    device["hash"] = _hash(token)  # the old address's cookie stops working
                    if address:
                        device["address"] = address
                    self._save()
                    return token
            return None

    def remove(self, index):
        """Forget one paired device (its position in devices())."""
        with self._lock:
            if 0 <= index < len(self._devices):
                del self._devices[index]
                self._save()

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
