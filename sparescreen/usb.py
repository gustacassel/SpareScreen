"""Conexão por USB: usa o adb para o celular enxergar o agente em localhost.

Com `adb reverse tcp:PORTA tcp:PORTA`, o `localhost:PORTA` do celular passa a
apontar para a mesma porta no PC, pelo cabo. Não precisa de Wi-Fi nem de root,
só da Depuração USB ligada no celular.
"""

import glob
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

# No Windows, evita abrir uma janela de console a cada chamada do adb.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def find_adb(explicit=None):
    """Procura o adb: caminho informado, PATH, SDK do Android e instalação via winget."""
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
    """Fica de olho nos celulares ligados por USB e mantém o `adb reverse` ativo."""

    def __init__(self, adb, port, open_page=True, stay_awake=False, poll_interval=3):
        self.adb = adb
        self.port = port
        self.open_page = open_page
        self.stay_awake = stay_awake
        self.poll_interval = poll_interval
        self._ready = set()   # celulares já configurados nesta conexão
        self._warned = set()  # celulares para os quais já avisamos de algum problema

    def start(self):
        threading.Thread(target=self._loop, name="usb", daemon=True).start()

    def _loop(self):
        while True:
            try:
                self._poll()
            except Exception as exc:
                print(f"[usb] erro: {exc}", flush=True)
            time.sleep(self.poll_interval)

    def _run(self, *args):
        result = subprocess.run(
            [self.adb, *args],
            capture_output=True, text=True, timeout=15, creationflags=_NO_WINDOW,
        )
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout).strip() or f"adb {args[0]} falhou")
        return result.stdout

    def _devices(self):
        """{serial: (estado, modelo)} a partir de `adb devices -l`."""
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
                print(f"[usb] {model}: aceite o pedido de \"Permitir depuração USB\" na tela do celular.", flush=True)

        # Celular desconectado: na próxima vez que ligar, configura de novo.
        connected = {s for s, (state, _) in devices.items() if state == "device"}
        for serial in self._ready - connected:
            print(f"[usb] celular {serial} desconectado.", flush=True)
        self._ready &= connected
        self._warned &= set(devices)

    def _ensure(self, serial, model):
        rule = f"tcp:{self.port}"
        # O reverse se perde se o servidor do adb reiniciar, então confere sempre.
        if f"{rule} {rule}" not in self._run("-s", serial, "reverse", "--list"):
            self._run("-s", serial, "reverse", rule, rule)

        if serial in self._ready:
            return
        self._ready.add(serial)
        self._warned.discard(serial)
        url = f"http://localhost:{self.port}"
        print(f"[usb] {model} conectado. No celular: {url}", flush=True)

        if self.stay_awake:
            self._run("-s", serial, "shell", "svc", "power", "stayon", "usb")
        if self.open_page:
            # O application_id faz o Chrome reaproveitar a mesma aba a cada reconexão.
            self._run(
                "-s", serial, "shell", "am", "start",
                "-a", "android.intent.action.VIEW", "-d", url,
                "--es", "com.android.browser.application_id", "sparescreen",
            )
