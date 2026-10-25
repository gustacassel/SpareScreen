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


# Android battery codes (BatteryManager.BATTERY_STATUS_* / BATTERY_HEALTH_*)
_STATUS = {2: "charging", 3: "discharging", 4: "not charging", 5: "full"}
_HEALTH = {2: "good", 3: "overheat", 4: "dead", 5: "over voltage", 6: "failure", 7: "cold"}


def parse_battery(text):
    """`adb shell dumpsys battery` -> {"level": 78, "temp": 32.5, "status": "charging", ...}."""
    values = {}
    for line in text.splitlines():
        key, sep, value = line.strip().partition(":")
        if sep:
            values[key.strip().lower()] = value.strip()

    def number(key):
        try:
            return int(values[key])
        except (KeyError, ValueError):
            return None

    temp = number("temperature")  # tenths of a degree Celsius
    level, scale = number("level"), number("scale") or 100
    return {
        "level": round(100 * level / scale) if level is not None else None,
        "temp": temp / 10 if temp is not None else None,
        "status": _STATUS.get(number("status"), "unknown"),
        "health": _HEALTH.get(number("health"), "unknown"),
        "plugged": any(values.get(k) == "true" for k in ("ac powered", "usb powered", "wireless powered")),
    }


class UsbBridge:
    """Watches the phones plugged in over USB, keeps `adb reverse` active and
    reads their battery (level, temperature, health) for the dashboard."""

    BATTERY_EVERY = 30  # seconds between battery readings

    def __init__(self, adb, port, open_page=True, stay_awake=False, poll_interval=3, screen=None):
        self.adb = adb
        self.port = port
        self.open_page = open_page
        self.stay_awake = stay_awake
        self.poll_interval = poll_interval
        self.screen = screen  # callable: "dim", "off" or None (see screen.py)
        self._rested = {}     # serial -> how its screen was rested, and what to put back
        self._ready = set()   # phones already set up on this connection
        self._warned = set()  # phones we have already warned about some problem
        self.batteries = {}   # serial -> latest battery reading (read by PhoneSource)
        self.phones = {}      # serial -> model of the phones ready right now (for the PC window)

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
        self.phones = {s: devices[s][1] for s in connected}
        for serial in self._ready - connected:
            print(f"[usb] phone {serial} disconnected.", flush=True)
        self._ready &= connected
        self._warned &= set(devices)
        for serial in list(self.batteries):
            if serial not in connected:
                del self.batteries[serial]

        for serial in list(self._rested):
            if serial not in connected:
                del self._rested[serial]

        wanted = self.screen() if self.screen else None
        for serial in connected:
            self._read_battery(serial, devices[serial][1])
            try:
                self._rest_screen(serial, wanted)
            except (RuntimeError, OSError, subprocess.SubprocessError):
                pass  # tried again on the next round

    def _rest_screen(self, serial, wanted):
        """Dims or turns off the phone's screen while `wanted`, and puts it back after."""
        rested = self._rested.get(serial)
        current = rested["how"] if rested else None
        if wanted == current:
            return
        if rested:
            self._wake(serial, rested)
            del self._rested[serial]
        if wanted == "dim":
            # Remember the user's brightness (and auto-brightness) to put them back later.
            saved = {name: self._run("-s", serial, "shell", "settings", "get", "system", name).strip()
                     for name in ("screen_brightness", "screen_brightness_mode")}
            self._run("-s", serial, "shell", "settings", "put", "system", "screen_brightness_mode", "0")
            self._run("-s", serial, "shell", "settings", "put", "system", "screen_brightness", "1")
            self._rested[serial] = {"how": "dim", "saved": saved}
        elif wanted == "off":
            self._run("-s", serial, "shell", "input", "keyevent", "KEYCODE_SLEEP")
            self._rested[serial] = {"how": "off"}

    def _wake(self, serial, rested):
        if rested["how"] == "dim":
            for name in ("screen_brightness", "screen_brightness_mode"):
                value = rested["saved"].get(name)
                if value and value.lstrip("-").isdigit():
                    self._run("-s", serial, "shell", "settings", "put", "system", name, value)
        elif rested["how"] == "off":
            self._run("-s", serial, "shell", "input", "keyevent", "KEYCODE_WAKEUP")

    def restore(self):
        """Puts every rested screen back (SpareScreen is closing)."""
        for serial, rested in list(self._rested.items()):
            try:
                self._wake(serial, rested)
            except (RuntimeError, OSError, subprocess.SubprocessError):
                pass
        self._rested.clear()

    def _read_battery(self, serial, model):
        last = self.batteries.get(serial)
        if last and time.time() - last["at"] < self.BATTERY_EVERY:
            return
        try:
            reading = parse_battery(self._run("-s", serial, "shell", "dumpsys", "battery"))
        except (RuntimeError, OSError, subprocess.SubprocessError):
            return
        reading.update(model=model, at=time.time())
        self.batteries[serial] = reading

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


class PhoneSource:
    """Battery of the phones on USB (level, temperature, health), for the top bar and
    the "battery is hot" alert. Phones on Wi-Fi only have what their browser reports."""

    name = "phone"

    def __init__(self, bridge=None):
        self.bridge = bridge

    def read(self):
        if not self.bridge:
            return {"devices": []}
        keys = ("model", "level", "temp", "status", "health", "plugged")
        return {"devices": [{k: b.get(k) for k in keys} for b in self.bridge.batteries.values()]}
