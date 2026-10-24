"""USB connection: uses adb so the phone can reach the agent on localhost.

With `adb reverse tcp:PORT tcp:PORT`, the phone's `localhost:PORT` points to
the same port on the PC, over the cable. No Wi-Fi or root needed, just USB
debugging turned on on the phone.
"""

import glob
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

# On Windows, avoids opening a console window on every adb call.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def find_adb(explicit=None):
    """Looks for adb: the given path, PATH, the Android SDK and a winget install."""
    if explicit:
        return explicit if Path(explicit).is_file() else None
    found = shutil.which("adb")
    if found:
        return found

    exe = "adb.exe" if sys.platform == "win32" else "adb"
    home = Path.home()
    candidates = [
        Path(os.environ[var]) / "platform-tools" / exe
        for var in ("ANDROID_HOME", "ANDROID_SDK_ROOT")
        if os.environ.get(var)
    ]
    if sys.platform == "win32":
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        candidates.append(local / "Android" / "Sdk" / "platform-tools" / exe)
        candidates.append(local / "Microsoft" / "WinGet" / "Links" / exe)
        candidates += map(Path, glob.glob(str(
            local / "Microsoft" / "WinGet" / "Packages" / "Google.PlatformTools*" / "platform-tools" / exe
        )))
    elif sys.platform == "darwin":
        candidates.append(home / "Library" / "Android" / "sdk" / "platform-tools" / exe)
        candidates.append(Path("/opt/homebrew/bin") / exe)
    else:
        candidates.append(home / "Android" / "Sdk" / "platform-tools" / exe)

    for path in candidates:
        if path.is_file():
            return str(path)
    return None


class UsbBridge:
    """Watches the phones plugged in over USB and keeps `adb reverse` active."""

    def __init__(self, adb, port, open_page=True, stay_awake=False, poll_interval=3):
        self.adb = adb
        self.port = port
        self.open_page = open_page
        self.stay_awake = stay_awake
        self.poll_interval = poll_interval
        self._ready = set()   # phones already set up on this connection
        self._warned = set()  # phones we have already warned about some problem

    def start(self):
        threading.Thread(target=self._loop, name="usb", daemon=True).start()

    def _loop(self):
        while True:
            try:
                self._poll()
            except Exception as exc:
                print(f"[usb] error: {exc}", flush=True)
            time.sleep(self.poll_interval)

    def _run(self, *args):
        result = subprocess.run(
            [self.adb, *args],
            capture_output=True, text=True, timeout=15, creationflags=_NO_WINDOW,
        )
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout).strip() or f"adb {args[0]} failed")
        return result.stdout

    def _devices(self):
        """{serial: (state, model)} from `adb devices -l`."""
        devices = {}
        for line in self._run("devices", "-l").splitlines()[1:]:
            parts = line.split()
            if len(parts) < 2:
                continue
            model = next((p[6:] for p in parts[2:] if p.startswith("model:")), parts[0])
            devices[parts[0]] = (parts[1], model.replace("_", " "))
        return devices

    def _poll(self):
        devices = self._devices()
        for serial, (state, model) in devices.items():
            if state == "device":
                self._ensure(serial, model)
            elif state == "unauthorized" and serial not in self._warned:
                self._warned.add(serial)
                print(f"[usb] {model}: accept the \"Allow USB debugging\" prompt on the phone screen.", flush=True)

        # Phone disconnected: set it up again the next time it is plugged in.
        connected = {s for s, (state, _) in devices.items() if state == "device"}
        for serial in self._ready - connected:
            print(f"[usb] phone {serial} disconnected.", flush=True)
        self._ready &= connected
        self._warned &= set(devices)

    def _ensure(self, serial, model):
        rule = f"tcp:{self.port}"
        # The reverse is lost if the adb server restarts, so always check it.
        if f"{rule} {rule}" not in self._run("-s", serial, "reverse", "--list"):
            self._run("-s", serial, "reverse", rule, rule)

        if serial in self._ready:
            return
        self._ready.add(serial)
        self._warned.discard(serial)
        url = f"http://localhost:{self.port}"
        print(f"[usb] {model} connected. On the phone: {url}", flush=True)

        if self.stay_awake:
            self._run("-s", serial, "shell", "svc", "power", "stayon", "usb")
        if self.open_page:
            # The application_id makes Chrome reuse the same tab on every reconnect.
            self._run(
                "-s", serial, "shell", "am", "start",
                "-a", "android.intent.action.VIEW", "-d", url,
                "--es", "com.android.browser.application_id", "sparescreen",
            )
