"""The PC window: what's missing (with a button to fix it), who is connected and pairing.

The server answers /panel/state and /panel/action to this machine only; the page is
web/panel.html, opened in an app window (appwindow.py). Checks are built from the
latest data snapshot, so they show what the dashboard actually gets.
"""

import re
import shutil
import subprocess
import sys
import time
import webbrowser

from . import autostart, lhm, names

# Shown as the device name; modern browsers hide the phone model, so this stays generic.
_SYSTEMS = (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"), ("CrOS", "ChromeOS"),
            ("Windows", "Windows"), ("Macintosh", "Mac"), ("Linux", "Linux"))
_BROWSERS = (("SamsungBrowser", "Samsung Internet"), ("Edg/", "Edge"), ("OPR/", "Opera"),
             ("Firefox", "Firefox"), ("Chrome", "Chrome"), ("Safari", "Safari"))


def describe_agent(agent):
    """'Mozilla/5.0 (Linux; Android 14; SM-A556E) ... Chrome/120' -> 'Android (SM-A556E) · Chrome'."""
    agent = agent or ""
    system = next((name for key, name in _SYSTEMS if key in agent), "Device")
    model = re.search(r"Android [\d.]+; ([^;)]+)\)", agent)
    if system == "Android" and model and model.group(1).strip() not in ("K", "wv"):
        system += f" ({model.group(1).strip()})"
    browser = next((name for key, name in _BROWSERS if key in agent), None)
    return system + (f" · {browser}" if browser else "")


def _mobile(agent):
    return any(key in (agent or "") for key in ("Android", "iPhone", "iPad", "Mobile"))


class Panel:
    def __init__(self, pairing=None, bridge=None, usb=True, info=None, local_url="", autostart_args=()):
        self.pairing = pairing
        self.bridge = bridge
        self.usb = usb  # False with --no-usb
        self.info = info or {}
        self.local_url = local_url
        self.autostart_args = list(autostart_args)
        self.hub = None  # set by server.serve()
        self.message = None  # result of the last action, shown once
        self.reachable = {}  # PC name -> when a phone last reached SpareScreen by it

    def name_works(self, name):
        self.reachable[name] = time.time()

    def addresses(self):
        """The PC's names (the ones a phone has reached first) and its IP, as URLs."""
        port = self.local_url.rsplit(":", 1)[-1] if self.local_url.count(":") == 2 else "8765"
        found = [{"url": f"http://{name}:{port}", "works": name in self.reachable}
                 for name in names.candidates()]
        found.sort(key=lambda a: not a["works"])
        return found

    # ---- state ---------------------------------------------------------------

    def state(self, clients):
        snapshot = self.hub.snapshot if self.hub else {}
        message, self.message = self.message, None
        return {
            "version": self.info.get("version"),
            "phone_url": self.info.get("phone_url"),
            "names": self.addresses() if self.info.get("phone_url") else [],
            "local_url": self.local_url,
            "code": self.pairing.code if self.pairing else None,
            "checks": self.checks(snapshot),
            "devices": self.devices(clients),
            "waiting": self._waiting(),
            "autostart": bool(autostart.status()),
            "autostart_label": "Start with Windows" if sys.platform == "win32" else "Start when I log in",
            "message": message,
        }

    def _waiting(self):
        waiting = self.pairing.waiting() if self.pairing else None
        if not waiting:
            return None
        return {"name": describe_agent(waiting["device"]), "address": waiting["address"],
                "ago": int(time.time() - waiting["at"])}

    def devices(self, clients):
        """What's connected now (open dashboards), the paired Wi-Fi device and USB phones."""
        usb_phones = dict(self.bridge.phones) if self.bridge else {}
        batteries = self.bridge.batteries if self.bridge else {}
        open_now = []
        for client in clients:
            agent = client.get("agent", "")
            if client.get("local") and _mobile(agent):
                kind = "usb"  # adb reverse: the phone reaches the PC through the cable
            elif client.get("local"):
                kind = "pc"
            else:
                kind = "wifi"
            open_now.append({"kind": kind, "name": describe_agent(agent), "address": client.get("address"),
                             "since": int(time.time() - client.get("since", time.time()))})
        phones = []
        for serial, model in usb_phones.items():
            battery = batteries.get(serial) or {}
            phones.append({"model": model, "level": battery.get("level"), "temp": battery.get("temp")})
        paired = []
        if self.pairing:
            for device in self.pairing.devices():
                paired.append({"name": describe_agent(device["device"]), "address": device.get("address"),
                               "added": device.get("added")})
        return {"open": open_now, "usb": phones, "paired": paired}

    def checks(self, snapshot):
        """[{"id", "status": ok|warn|error|info, "title", "detail", "action": {"id", "label"}|None}]"""
        system = snapshot.get("system") or {}
        items = [self._sensors_check(system), self._gpu_check(system), self._usb_check(),
                 self._wifi_check(), self._ai_check(snapshot), self._media_check(snapshot)]
        return [item for item in items if item]

    @staticmethod
    def _check(id, status, title, detail="", action=None, label=None):
        return {"id": id, "status": status, "title": title, "detail": detail,
                "action": {"id": action, "label": label} if action else None}

    def _sensors_check(self, system):
        cpu = system.get("cpu") or {}
        temp = cpu.get("temp")
        if sys.platform == "win32":
            if temp is not None:
                return self._check("sensors", "ok", "CPU sensors",
                                   f"LibreHardwareMonitor is running · CPU {round(temp)} °C")
            exe = lhm.find()
            if not exe:
                return self._check("sensors", "error", "CPU sensors",
                                   "CPU temperature, clocks and fans need LibreHardwareMonitor (free).",
                                   "lhm_install", "Install")
            if not lhm.running():
                return self._check("sensors", "warn", "CPU sensors",
                                   "LibreHardwareMonitor is installed but closed. Windows will ask for "
                                   "admin rights to open it.", "lhm_start", "Open it")
            return self._check("sensors", "warn", "CPU sensors",
                               "LibreHardwareMonitor is open but its web server is off: in it, "
                               "Options > Remote Web Server > Run.")
        if temp is not None:
            return self._check("sensors", "ok", "CPU sensors", f"CPU {round(temp)} °C")
        if sys.platform == "darwin":
            return self._check("sensors", "warn", "CPU sensors",
                               "No CPU temperature: install smctemp, macmon or osx-cpu-temp (see the README).")
        return self._check("sensors", "warn", "CPU sensors",
                           "No CPU temperature sensor found (on many PCs the lm-sensors package helps).")

    def _gpu_check(self, system):
        gpu = system.get("gpu")
        if gpu:
            return self._check("gpu", "ok", "GPU", gpu.get("name") or "Reading the GPU")
        detail = "No GPU data. NVIDIA cards need their driver (nvidia-smi)"
        detail += "; AMD and Intel need LibreHardwareMonitor." if sys.platform == "win32" else "."
        return self._check("gpu", "info", "GPU", detail)

    def _usb_check(self):
        if not self.usb:
            return self._check("usb", "info", "USB cable", "Turned off (--no-usb).")
        if not self.bridge:
            if sys.platform == "win32" and shutil.which("winget"):
                return self._check("usb", "warn", "USB cable",
                                   "To use a USB cable, the PC needs adb (Android Platform Tools, free). "
                                   "Restart SpareScreen after installing it.", "adb_install", "Install")
            return self._check("usb", "warn", "USB cable",
                               "To use a USB cable, install adb (Android Platform Tools; see the README).")
        phones = list(self.bridge.phones.values())
        if phones:
            return self._check("usb", "ok", "USB cable", "Connected: " + ", ".join(phones))
        return self._check("usb", "ok", "USB cable",
                           "Ready: plug in an Android phone with USB debugging on.")

    def _wifi_check(self):
        url = self.info.get("phone_url")
        if url:
            return self._check("wifi", "ok", "Wi-Fi", f"On a phone on the same network, open {url}")
        return self._check("wifi", "info", "Wi-Fi", "Off: SpareScreen only listens on this PC (--host).")

    @staticmethod
    def _ai_check(snapshot):
        found = [(snapshot.get(key) or {}).get("name") or label
                 for key, label in (("claude", "Claude Code"), ("codex", "Codex"))
                 if (snapshot.get(key) or {}).get("installed")]
        if found:
            return Panel._check("ai", "ok", "AI tools", ", ".join(found))
        return Panel._check("ai", "info", "AI tools", "No Claude Code or Codex found: the AI screen stays hidden.")

    @staticmethod
    def _media_check(snapshot):
        media = snapshot.get("media") or {}
        if media.get("available"):
            return Panel._check("media", "ok", "Now playing", media.get("title") or "Nothing playing right now")
        return Panel._check("media", "info", "Now playing", "Not available on this system (see the README).")

    # ---- actions ------------------------------------------------------------

    def act(self, action, data=None):
        data = data or {}
        if action == "lhm_start":
            exe = lhm.find()
            error = lhm.start(exe) if exe else "LibreHardwareMonitor isn't installed."
            self.message = error or "Starting LibreHardwareMonitor (it goes to the tray)."
        elif action == "lhm_install":
            self.message = lhm.install() or "Installing in the console window; then click Open it."
        elif action == "adb_install":
            winget = shutil.which("winget")
            if winget:
                subprocess.Popen([winget, "install", "--id", "Google.PlatformTools", "--exact"],
                                 creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
                self.message = "Installing in the console window; then restart SpareScreen."
            else:
                self.message = "winget isn't available: see the README to install adb."
        elif action == "unpair" and self.pairing:
            try:
                self.pairing.remove(int(data.get("index")))
            except (TypeError, ValueError):
                return {"ok": False}
            self.message = "Device removed. It will ask for the code again."
        elif action == "autostart":
            if data.get("on"):
                autostart.enable(self.autostart_args)
            else:
                autostart.disable()
        elif action == "dashboard":
            webbrowser.open(self.local_url)
        else:
            return {"ok": False}
        return {"ok": True, "message": self.message}
