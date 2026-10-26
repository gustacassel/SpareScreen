"""The PC window: what's missing (with a button to fix it), who is connected and pairing.

The server answers /panel/state and /panel/action to this machine only; the page is
web/panel.html, opened in an app window (appwindow.py). Checks are built from the
latest data snapshot, so they show what the dashboard actually gets.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
import webbrowser
from typing import TYPE_CHECKING, Any, Iterable, Optional

from . import autostart, fps, lhm, names
from . import photos as photo_folder
from .games import same_exe
from .shapes import Activity, Check, Json

if TYPE_CHECKING:
    from .config import ConfigStore
    from .pairing import Pairing
    from .photos import Photos
    from .server import Hub
    from .update import Updater
    from .usb import UsbBridge

# Shown as the device name; modern browsers hide the phone model, so this stays generic.
_SYSTEMS = (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"), ("CrOS", "ChromeOS"),
            ("Windows", "Windows"), ("Macintosh", "Mac"), ("Linux", "Linux"))
_BROWSERS = (("SamsungBrowser", "Samsung Internet"), ("Edg/", "Edge"), ("OPR/", "Opera"),
             ("Firefox", "Firefox"), ("Chrome", "Chrome"), ("Safari", "Safari"))


def describe_agent(agent: Optional[str]) -> str:
    """'Mozilla/5.0 (Linux; Android 14; SM-A556E) ... Chrome/120' -> 'Android (SM-A556E) · Chrome'."""
    agent = agent or ""
    system = next((name for key, name in _SYSTEMS if key in agent), "Device")
    model = re.search(r"Android [\d.]+; ([^;)]+)\)", agent)
    if system == "Android" and model and model.group(1).strip() not in ("K", "wv"):
        system += f" ({model.group(1).strip()})"
    browser = next((name for key, name in _BROWSERS if key in agent), None)
    return system + (f" · {browser}" if browser else "")


def _mobile(agent: Optional[str]) -> bool:
    return any(key in (agent or "") for key in ("Android", "iPhone", "iPad", "Mobile"))


class Panel:
    def __init__(self, pairing: Optional[Pairing] = None, bridge: Optional[UsbBridge] = None, usb: bool = True,
                 info: Optional[Json] = None, local_url: str = "", autostart_args: Iterable[str] = (),
                 config: Optional[ConfigStore] = None, activity: Optional[Activity] = None,
                 updater: Optional[Updater] = None, photos: Optional[Photos] = None) -> None:
        self.pairing = pairing
        self.updater = updater
        self.photos = photos
        self.config = config
        self.activity = activity
        self.bridge = bridge
        self.usb = usb  # False with --no-usb
        self.info = info or {}
        self.local_url = local_url
        self.autostart_args = list(autostart_args)
        self.hub: Optional[Hub] = None  # set by server.serve()
        self.message: Optional[str] = None  # result of the last action, shown once
        self.reachable: dict[str, float] = {}  # PC name -> when a phone last reached SpareScreen by it

    def name_works(self, name: str) -> None:
        self.reachable[name] = time.time()

    def addresses(self) -> list[Json]:
        """The PC's names (the ones a phone has reached first) and its IP, as URLs."""
        port = self.local_url.rsplit(":", 1)[-1] if self.local_url.count(":") == 2 else "8765"
        found = [{"url": f"http://{name}:{port}", "works": name in self.reachable}
                 for name in names.candidates()]
        found.sort(key=lambda a: not a["works"])
        return found

    # ---- state ---------------------------------------------------------------

    def state(self, clients: list[Json]) -> Json:
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
            "games": self.games(snapshot),
            "update": self.updater.state() if self.updater else None,
            "display": self.display(),
            "autostart": bool(autostart.status()),
            "autostart_label": "Start with Windows" if sys.platform == "win32" else "Start when I log in",
            "message": message,
        }

    def display(self) -> Optional[Json]:
        """The Display tab: the photo folder and the scrolling message."""
        if not self.config:
            return None
        found = self.photos.status() if self.photos else {"count": 0, "error": None}
        return {"folder": self.config.photos_dir(), "count": found["count"], "error": found["error"],
                "can_pick": photo_folder.can_pick(), "banner": self.config.read().get("banner", "")}

    def _waiting(self) -> Optional[Json]:
        waiting = self.pairing.waiting() if self.pairing else None
        if not waiting:
            return None
        return {"name": describe_agent(waiting["device"]), "address": waiting["address"],
                "ago": int(time.time() - waiting["at"])}

    def games(self, snapshot: Json) -> Json:
        """The game now (and how it was recognized), the user's lists, and what's running."""
        game = (snapshot.get("activity") or {}).get("game")
        lists = self.config.games() if self.config else {"my_games": [], "not_games": []}
        listed = {same_exe(g["exe"]) for g in lists["my_games"]} | {same_exe(p) for p in lists["not_games"]}
        running = [r for r in (self.activity.running if self.activity else []) if same_exe(r["exe"]) not in listed]
        return {
            "current": {"name": game["name"], "source": game.get("source", "library")} if game else None,
            "mine": lists["my_games"],
            "not_games": [{"exe": p, "name": os.path.basename(p)} for p in lists["not_games"]],
            "running": running,
            "auto": fps.AutoDetect.ready(),
        }

    def devices(self, clients: list[Json]) -> Json:
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

    def checks(self, snapshot: Json) -> list[Check]:
        """[{"id", "status": ok|warn|error|info, "title", "detail", "action": {"id", "label"}|None}]"""
        system = snapshot.get("system") or {}
        items = [self._sensors_check(system), self._gpu_check(system), self._fps_check(snapshot),
                 self._usb_check(), self._wifi_check(), self._ai_check(snapshot), self._media_check(snapshot),
                 self._update_check()]
        return [item for item in items if item]

    @staticmethod
    def _check(id: str, status: str, title: str, detail: str = "", action: Optional[str] = None,
               label: str = "") -> Check:
        return {"id": id, "status": status, "title": title, "detail": detail,
                "action": {"id": action, "label": label} if action else None}

    def _sensors_check(self, system: Json) -> Check:
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

    def _gpu_check(self, system: Json) -> Check:
        gpu = system.get("gpu")
        if gpu:
            return self._check("gpu", "ok", "GPU", gpu.get("name") or "Reading the GPU")
        detail = "No GPU data. NVIDIA cards need their driver (nvidia-smi)"
        detail += "; AMD and Intel need LibreHardwareMonitor." if sys.platform == "win32" else "."
        return self._check("gpu", "info", "GPU", detail)

    def _fps_check(self, snapshot: Json) -> Optional[Check]:
        if sys.platform != "win32":
            return None  # PresentMon is Windows only
        title = "FPS in games"
        if fps.find_presentmon() and fps.allowed():
            reading = snapshot.get("fps") or {}
            if reading.get("playing") and reading.get("error") == "failed":
                return self._check("fps", "warn", title, "PresentMon couldn't follow this game.")
            if reading.get("playing") and reading.get("fps"):
                return self._check("fps", "ok", title, f"{reading['fps']} FPS right now")
            return self._check("fps", "ok", title, "Ready: shows on the game screen while you play.")
        if fps.find_presentmon() and fps.requested():
            return self._check("fps", "warn", title,
                               "Sign out of Windows and back in to finish turning it on.")
        return self._check("fps", "info", title,
                           "Show the FPS of the game you're playing. Uses PresentMon (free, from Intel; "
                           "downloaded once) and asks Windows once for permission to read frame "
                           "timings (the \"Performance Log Users\" group).", "fps_enable", "Enable")

    def _usb_check(self) -> Check:
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

    def _wifi_check(self) -> Check:
        url = self.info.get("phone_url")
        if url:
            return self._check("wifi", "ok", "Wi-Fi", f"On a phone on the same network, open {url}")
        return self._check("wifi", "info", "Wi-Fi", "Off: SpareScreen only listens on this PC (--host).")

    @staticmethod
    def _ai_check(snapshot: Json) -> Check:
        found = [(snapshot.get(key) or {}).get("name") or label
                 for key, label in (("claude", "Claude Code"), ("codex", "Codex"), ("gemini", "Gemini CLI"))
                 if (snapshot.get(key) or {}).get("installed")]
        if found:
            return Panel._check("ai", "ok", "AI tools", ", ".join(found))
        return Panel._check("ai", "info", "AI tools",
                            "No Claude Code, Codex or Gemini CLI found: the AI screen stays hidden.")

    @staticmethod
    def _media_check(snapshot: Json) -> Check:
        media = snapshot.get("media") or {}
        if media.get("available"):
            return Panel._check("media", "ok", "Now playing", media.get("title") or "Nothing playing right now")
        return Panel._check("media", "info", "Now playing", "Not available on this system (see the README).")

    def _update_check(self) -> Optional[Check]:
        if not self.updater:
            return None
        update = self.updater.state()
        if update["latest"]:
            return self._check("update", "info", "Updates", f"SpareScreen {update['latest']} is available.")
        if update["error"]:
            return self._check("update", "warn", "Updates", update["error"], "update_check_now", "Try again")
        if update["checked_at"]:
            return self._check("update", "ok", "Updates", f"Up to date ({update['current']}).",
                               "update_check_now", "Check now")
        detail = "Checks GitHub for new versions now and then." if update["enabled"] else "Automatic check off."
        return self._check("update", "info", "Updates", detail, "update_check_now", "Check now")

    # ---- actions ------------------------------------------------------------

    def _edit_games(self, action: str, data: Json) -> None:
        assert self.config is not None  # act() only edits the lists with a config
        lists = self.config.games()
        mine, others = lists["my_games"], lists["not_games"]
        exe = data.get("exe") if isinstance(data.get("exe"), str) else None
        if action == "not_game_add" and not exe and self.activity:
            exe = self.activity.game_exe  # "not a game" on the game being shown
        if not exe:
            return
        same = same_exe(exe)
        mine = [g for g in mine if same_exe(g["exe"]) != same]
        others = [p for p in others if same_exe(p) != same]
        if action == "game_add":
            mine.append({"exe": exe, "name": str(data.get("name") or "")})
            self.message = "Added to your games."
        elif action == "not_game_add":
            others.append(exe)
            self.message = "Won't be taken for a game again."
        self.config.set_games(mine, others)
        if self.activity:
            self.activity.refresh_soon()  # look again now, not in a few seconds

    def _set_photos(self, action: str, data: Json) -> None:
        assert self.config is not None  # act() only gets here with a config
        if action == "photos_clear":
            folder = None
        elif action == "photos_pick":
            folder = photo_folder.pick_folder()  # waits for the dialog on this PC
            if not folder:
                return
        else:
            typed = data.get("folder")
            folder = os.path.expanduser(typed.strip()) if isinstance(typed, str) and typed.strip() else None
            if not folder or not os.path.isdir(folder):
                self.message = "That folder doesn't exist on this PC."
                return
        self.config.set_photos_dir(folder)
        if self.photos:
            self.photos.rescan()
        if folder is None:
            self.message = "No photos: the Photos screen is hidden."
        else:
            count = self.photos.status()["count"] if self.photos else 0
            self.message = f"{count} photos found." if count else "No photos in that folder (JPG, PNG, WebP or GIF)."

    def act(self, action: str, data: Optional[Json] = None) -> Json:
        data = data or {}
        if action == "lhm_start":
            exe = lhm.find()
            error = lhm.start(exe) if exe else "LibreHardwareMonitor isn't installed."
            self.message = error or "Starting LibreHardwareMonitor (it goes to the tray)."
        elif action == "lhm_install":
            self.message = lhm.install() or "Installing in the console window; then click Open it."
        elif action in ("game_add", "game_remove", "not_game_add", "not_game_remove") and self.config:
            self._edit_games(action, data)
        elif action == "fps_enable":
            self.message = fps.enable()
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
                index: Any = data.get("index")  # from the page: int() checks it
                self.pairing.remove(int(index))
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
        elif action in ("photos_pick", "photos_set", "photos_clear") and self.config:
            self._set_photos(action, data)
        elif action == "banner_set" and self.config:
            text = data.get("text")
            self.config.set_banner(text if isinstance(text, str) else "")
            self.message = "Message saved." if self.config.read()["banner"] else "Message removed."
        elif action == "update_install" and self.updater:
            self.updater.install()
        elif action == "update_check_now" and self.updater:
            self.updater.check_now()
        elif action == "update_auto" and self.config:
            self.config.update({"update_check": bool(data.get("on"))})
        elif action == "update_notes" and self.updater:
            webbrowser.open(self.updater.state()["url"])
        else:
            return {"ok": False}
        return {"ok": True, "message": self.message}
