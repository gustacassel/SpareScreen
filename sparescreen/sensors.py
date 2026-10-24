"""Temperatures, fans, drives and GPU, which every OS exposes differently.

- GPU: `nvidia-smi` for NVIDIA (Windows and Linux, no admin needed). Otherwise
  LibreHardwareMonitor on Windows (NVIDIA, AMD and Intel) or the `amdgpu`
  driver's sysfs files on Linux.
- Windows: LibreHardwareMonitor with its "Remote Web Server" enabled, for CPU,
  fans and drives. Windows only exposes these sensors to programs that ship
  their own driver.
- Linux: `psutil.sensors_temperatures()` and `sensors_fans()` (hwmon).
"""

import glob
import json
import os
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
_SIZE_UNITS = {"B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3}
MIB = 1024 * 1024


def _number(text):
    """'45,3 °C' -> 45.3; '[N/A]' -> None. LHM formats numbers in the Windows locale."""
    match = _NUMBER.search(text or "")
    return float(match.group().replace(",", ".")) if match else None


def _with_unit(text, units):
    """'111,6 KB/s' -> bytes per second; '1924,0 MB' -> bytes."""
    value = _number(text)
    unit = (text or "").split()[-1] if text else ""
    return value * units.get(unit, 1) if value is not None else None


def _first(values, names):
    """First non-empty value among `names`, in order of preference."""
    return next((values[n] for n in names if values.get(n) is not None), None)


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
        # First card only, for now.
        fields = [p.strip() for p in result.stdout.splitlines()[0].split(",")]
        name, util, temp, used, total, power, fan, clock, mem_clock = fields
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
    """Reads /data.json from LibreHardwareMonitor's web server."""

    CPU_TEMP_NAMES = ("Core (Tctl/Tdie)", "CPU Package", "Core (Tctl)", "Core (Tdie)", "Package")
    DRIVE_TEMP_NAMES = ("Composite Temperature", "Temperature")
    GPU_TEMP_NAMES = ("GPU Core", "GPU Hot Spot")
    GPU_LOAD_NAMES = ("GPU Core", "D3D 3D")
    GPU_POWER_NAMES = ("GPU Package", "GPU Power", "GPU Core")
    RETRY_AFTER = 30  # if it did not answer, wait before trying again

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

        result = {"cpu": None, "gpu": None, "fans": [], "drives": []}
        gpus = []
        for hardware in self._hardware(tree):
            kind = (hardware.get("ImageURL") or "").lower()
            is_gpu = (hardware.get("HardwareId") or "").startswith("/gpu")
            if "cpu" in kind and result["cpu"] is None:
                result["cpu"] = self._cpu(hardware)
            elif "hdd" in kind:
                result["drives"].append(self._drive(hardware))
            elif is_gpu:
                gpus.append(self._gpu(hardware))
            result["fans"] += self._fans(hardware, gpu=is_gpu)
        if gpus:
            # Prefer a dedicated card (the one with the most memory) over integrated graphics.
            result["gpu"] = max(gpus, key=lambda g: (not g["integrated"], g["mem_total"] or 0))
        return result

    @classmethod
    def _hardware(cls, node):
        """Every component, including those nested in others (the motherboard's sensor chip)."""
        for child in node.get("Children", []):
            if "HardwareId" in child:
                yield child
            if "SensorId" not in child:
                yield from cls._hardware(child)

    @staticmethod
    def _raw_group(hardware, name):
        """Sensors of a group ("Temperatures", "Data"...), merging groups that share a name."""
        values = {}
        for group in hardware.get("Children", []):
            if group.get("Text") == name and "HardwareId" not in group:
                values.update({s.get("Text"): s.get("Value") for s in group.get("Children", [])})
        return values

    @classmethod
    def _group(cls, hardware, name):
        return {k: _number(v) for k, v in cls._raw_group(hardware, name).items()}

    def _cpu(self, hardware):
        temps = self._group(hardware, "Temperatures")
        temp = _first(temps, self.CPU_TEMP_NAMES)
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

    def _gpu(self, hardware):
        data = self._raw_group(hardware, "Data")
        clocks = self._group(hardware, "Clocks")
        controls = self._group(hardware, "Controls")
        return {
            "name": short_gpu_name(hardware.get("Text") or "GPU"),
            "percent": _first(self._group(hardware, "Load"), self.GPU_LOAD_NAMES),
            "temp": _first(self._group(hardware, "Temperatures"), self.GPU_TEMP_NAMES),
            "mem_used": _with_unit(data.get("GPU Memory Used"), _SIZE_UNITS),
            "mem_total": _with_unit(data.get("GPU Memory Total"), _SIZE_UNITS),
            "power": _first(self._group(hardware, "Powers"), self.GPU_POWER_NAMES),
            "fan": next(iter(controls.values()), None),
            "clock": clocks.get("GPU Core"),
            "mem_clock": clocks.get("GPU Memory"),
            "integrated": "integrated" in (hardware.get("HardwareId") or ""),
        }

    def _drive(self, hardware):
        temps = self._group(hardware, "Temperatures")
        rates = self._raw_group(hardware, "Throughput")
        return {
            "name": hardware.get("Text"),
            "temp": _first(temps, self.DRIVE_TEMP_NAMES),
            "read": _with_unit(rates.get("Read Rate"), _RATE_UNITS),
            "write": _with_unit(rates.get("Write Rate"), _RATE_UNITS),
        }

    def _fans(self, hardware, gpu):
        rpms = self._group(hardware, "Fans")
        percents = self._group(hardware, "Controls")
        fans = []
        for name, rpm in rpms.items():
            if rpm is None or (rpm == 0 and not gpu):  # motherboard fan at 0 rpm: empty header
                continue
            fans.append({
                "name": "GPU" if gpu else name.replace("#", "").strip(),
                "rpm": rpm,
                "percent": percents.get(name),
                "gpu": gpu,
            })
        return fans


def _read_file(path, scale=1.0):
    """Number from a sysfs file (None if it does not exist)."""
    try:
        with open(path, encoding="utf-8") as f:
            return float(f.read().strip()) / scale
    except (OSError, ValueError):
        return None


def _current_dpm_clock(path):
    """Active clock from pp_dpm_sclk/pp_dpm_mclk: the line marked with '*' ('1: 2100Mhz *')."""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.rstrip().endswith("*"):
                    return _number(line.split(":", 1)[1])
    except OSError:
        pass
    return None


def linux_amd_gpu(drm="/sys/class/drm"):
    """AMD GPU on Linux via the amdgpu driver's sysfs files (no root needed)."""
    for card in sorted(glob.glob(os.path.join(drm, "card[0-9]*"))):
        dev = os.path.join(card, "device")
        busy = _read_file(os.path.join(dev, "gpu_busy_percent"))
        if busy is None:
            continue
        hwmon = (glob.glob(os.path.join(dev, "hwmon", "hwmon*")) or [""])[0]
        try:
            with open(os.path.join(dev, "product_name"), encoding="utf-8") as f:
                name = f.read().strip()
        except OSError:
            name = "AMD GPU"
        return {
            "name": short_gpu_name(name),
            "percent": busy,
            "temp": _read_file(os.path.join(hwmon, "temp1_input"), 1000),
            "mem_used": _read_file(os.path.join(dev, "mem_info_vram_used")),
            "mem_total": _read_file(os.path.join(dev, "mem_info_vram_total")),
            "power": _read_file(os.path.join(hwmon, "power1_average"), 1e6)
            or _read_file(os.path.join(hwmon, "power1_input"), 1e6),
            "fan": None,
            "fan_rpm": _read_file(os.path.join(hwmon, "fan1_input")),
            "clock": _current_dpm_clock(os.path.join(dev, "pp_dpm_sclk")),
            "mem_clock": _current_dpm_clock(os.path.join(dev, "pp_dpm_mclk")),
        }
    return None


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
        if chip == "amdgpu":  # shown as the GPU fan instead
            continue
        for i, fan in enumerate(entries):
            if fan.current:
                fans.append({"name": fan.label or f"{chip} {i + 1}", "rpm": fan.current, "percent": None, "gpu": False})
    return fans


class Sensors:
    """Combines the sources above and caches the result for a few seconds."""

    def __init__(self, refresh=2):
        self.refresh = refresh
        self.nvidia = NvidiaGpu()
        self.lhm = LibreHardwareMonitor() if sys.platform == "win32" else None
        self._at = 0
        self._cache = {"cpu_temp": None, "cpu_power": None, "cpu_clock": None, "cpu_clock_max": None,
                       "gpu": None, "fans": [], "drives": []}

    def read(self):
        if time.time() - self._at < self.refresh:
            return self._cache
        self._at = time.time()
        cpu, fans, drives, gpu = {}, [], [], None
        if self.lhm:
            lhm = self.lhm.read() or {}
            cpu, fans, drives, gpu = lhm.get("cpu") or {}, lhm.get("fans", []), lhm.get("drives", []), lhm.get("gpu")
        elif sys.platform.startswith("linux"):
            freq = psutil.cpu_freq()
            cpu, fans = {"temp": linux_cpu_temp(), "clock": freq.current if freq else None}, linux_fans()
            gpu = linux_amd_gpu()

        # nvidia-smi is the most reliable source for NVIDIA cards, so it wins when present.
        gpu = self.nvidia.read() or gpu
        if gpu and not any(f["gpu"] for f in fans) and (gpu.get("fan") is not None or gpu.get("fan_rpm")):
            fans.append({"name": "GPU", "rpm": gpu.get("fan_rpm"), "percent": gpu.get("fan"), "gpu": True})
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
