"""Temperaturas, ventoinhas, discos e GPU, que cada sistema expõe de um jeito.

- GPU NVIDIA: `nvidia-smi` (Windows e Linux, sem precisar de admin).
- Windows: LibreHardwareMonitor com o "Remote Web Server" ligado, para CPU,
  ventoinhas e discos. O Windows só libera esses sensores para programas com
  driver próprio.
- Linux: `psutil.sensors_temperatures()` e `sensors_fans()` (hwmon).
"""

import json
import re
import shutil
import subprocess
import sys
import time
import urllib.request

import psutil

from .hwinfo import short_gpu_name

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_NUMBER = re.compile(r"-?\d+(?:[.,]\d+)?")
_RATE_UNITS = {"B/s": 1, "KB/s": 1024, "MB/s": 1024 ** 2, "GB/s": 1024 ** 3}
MIB = 1024 * 1024


def _number(text):
    """'45,3 °C' -> 45.3; '[N/A]' -> None. O LHM formata no idioma do Windows."""
    match = _NUMBER.search(text or "")
    return float(match.group().replace(",", ".")) if match else None


def _rate(text):
    """'111,6 KB/s' -> bytes por segundo."""
    value = _number(text)
    unit = (text or "").split()[-1] if text else ""
    return value * _RATE_UNITS.get(unit, 1) if value is not None else None


class NvidiaGpu:
    QUERY = "name,utilization.gpu,temperature.gpu,memory.used,memory.total,power.draw,fan.speed,clocks.gr,clocks.mem"

    def __init__(self):
        self.exe = shutil.which("nvidia-smi")

    def read(self):
        if not self.exe:
            return None
        result = subprocess.run(
            [self.exe, f"--query-gpu={self.QUERY}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, creationflags=_NO_WINDOW,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        # Só a primeira placa, por enquanto.
        name, util, temp, used, total, power, fan, clock, mem_clock =             [p.strip() for p in result.stdout.splitlines()[0].split(",")]
        used, total = _number(used), _number(total)
        return {
            "name": short_gpu_name(name),
            "percent": _number(util),
            "temp": _number(temp),
            "mem_used": used * MIB if used is not None else None,
            "mem_total": total * MIB if total is not None else None,
            "power": _number(power),
            "fan": _number(fan),
            "clock": _number(clock),
            "mem_clock": _number(mem_clock),
        }


class LibreHardwareMonitor:
    """Lê o /data.json do servidor web do LibreHardwareMonitor."""

    CPU_TEMP_NAMES = ("Core (Tctl/Tdie)", "CPU Package", "Core (Tctl)", "Core (Tdie)", "Package")
    DRIVE_TEMP_NAMES = ("Composite Temperature", "Temperature")
    RETRY_AFTER = 30  # se não respondeu, espera antes de tentar de novo

    def __init__(self, url="http://localhost:8085/data.json"):
        self.url = url
        self._down_until = 0

    def read(self):
        if time.time() < self._down_until:
            return None
        try:
            with urllib.request.urlopen(self.url, timeout=1) as resp:
                tree = json.load(resp)
        except (OSError, ValueError):
            self._down_until = time.time() + self.RETRY_AFTER
            return None

        result = {"cpu": None, "fans": [], "drives": []}
        for hardware in self._hardware(tree):
            kind = (hardware.get("ImageURL") or "").lower()
            if "cpu" in kind and result["cpu"] is None:
                result["cpu"] = self._cpu(hardware)
            elif "hdd" in kind:
                result["drives"].append(self._drive(hardware))
            result["fans"] += self._fans(hardware, gpu="nvidia" in kind or "ati" in kind or "gpu" in kind)
        return result

    @classmethod
    def _hardware(cls, node):
        """Todas as peças, inclusive as de dentro de outras (o chip de sensores da placa-mãe)."""
        for child in node.get("Children", []):
            if "HardwareId" in child:
                yield child
            if "SensorId" not in child:
                yield from cls._hardware(child)

    @staticmethod
    def _raw_group(hardware, name):
        for group in hardware.get("Children", []):
            if group.get("Text") == name and "HardwareId" not in group:
                return {s.get("Text"): s.get("Value") for s in group.get("Children", [])}
        return {}

    @classmethod
    def _group(cls, hardware, name):
        return {k: _number(v) for k, v in cls._raw_group(hardware, name).items()}

    def _cpu(self, hardware):
        temps = self._group(hardware, "Temperatures")
        temp = next((temps[n] for n in self.CPU_TEMP_NAMES if temps.get(n) is not None), None)
        if temp is None:
            temp = max((t for t in temps.values() if t is not None), default=None)
        clocks = self._group(hardware, "Clocks")
        cores = [v for k, v in clocks.items() if k.startswith("Core #") and "Effective" not in k and v]
        average = clocks.get("Cores (Average)") or (sum(cores) / len(cores) if cores else None)
        return {
            "temp": temp,
            "power": self._group(hardware, "Powers").get("Package"),
            "clock": average,
            "clock_max": max(cores) if cores else None,
        }

    def _drive(self, hardware):
        temps = self._group(hardware, "Temperatures")
        rates = self._raw_group(hardware, "Throughput")
        return {
            "name": hardware.get("Text"),
            "temp": next((temps[n] for n in self.DRIVE_TEMP_NAMES if temps.get(n) is not None), None),
            "read": _rate(rates.get("Read Rate")),
            "write": _rate(rates.get("Write Rate")),
        }

    def _fans(self, hardware, gpu):
        rpms = self._group(hardware, "Fans")
        percents = self._group(hardware, "Controls")
        fans = []
        for name, rpm in rpms.items():
            if rpm is None or (rpm == 0 and not gpu):  # fan da placa em 0 rpm: conector vazio
                continue
            fans.append({
                "name": "GPU" if gpu else name.replace("#", "").strip(),
                "rpm": rpm,
                "percent": percents.get(name),
                "gpu": gpu,
            })
        return fans


def linux_cpu_temp():
    temps = psutil.sensors_temperatures()
    for chip, labels in (("k10temp", ("Tctl", "Tdie")), ("zenpower", ("Tdie",)),
                         ("coretemp", ("Package id 0",)), ("cpu_thermal", ("",))):
        for sensor in temps.get(chip, []):
            if sensor.label in labels:
                return sensor.current
    return None


def linux_fans():
    fans = []
    for chip, entries in (psutil.sensors_fans() or {}).items():
        for i, fan in enumerate(entries):
            if fan.current:
                fans.append({"name": fan.label or f"{chip} {i + 1}", "rpm": fan.current, "percent": None, "gpu": False})
    return fans


class Sensors:
    """Junta as fontes acima e guarda o resultado por alguns segundos."""

    def __init__(self, refresh=2):
        self.refresh = refresh
        self.gpu = NvidiaGpu()
        self.lhm = LibreHardwareMonitor() if sys.platform == "win32" else None
        self._at = 0
        self._cache = {"cpu_temp": None, "cpu_power": None, "cpu_clock": None, "cpu_clock_max": None,
                       "gpu": None, "fans": [], "drives": []}

    def read(self):
        if time.time() - self._at < self.refresh:
            return self._cache
        self._at = time.time()
        cpu, fans, drives = {}, [], []
        if self.lhm:
            lhm = self.lhm.read() or {}
            cpu, fans, drives = lhm.get("cpu") or {}, lhm.get("fans", []), lhm.get("drives", [])
        elif sys.platform.startswith("linux"):
            freq = psutil.cpu_freq()
            cpu, fans = {"temp": linux_cpu_temp(), "clock": freq.current if freq else None}, linux_fans()
        gpu = self.gpu.read()
        if gpu and not any(f["gpu"] for f in fans) and gpu["fan"] is not None:
            fans.append({"name": "GPU", "rpm": None, "percent": gpu["fan"], "gpu": True})
        self._cache = {
            "cpu_temp": cpu.get("temp"),
            "cpu_power": cpu.get("power"),
            "cpu_clock": cpu.get("clock"),
            "cpu_clock_max": cpu.get("clock_max"),
            "gpu": gpu,
            "fans": fans,
            "drives": drives,
        }
        return self._cache
