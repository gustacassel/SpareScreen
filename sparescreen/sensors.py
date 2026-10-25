"""Temperatures, fans, drives and GPU, which every OS exposes differently.

- GPU: `nvidia-smi` for NVIDIA (Windows and Linux, no admin needed). Otherwise
  LibreHardwareMonitor on Windows (NVIDIA, AMD and Intel) or the `amdgpu`
  driver's sysfs files on Linux.
- Windows: LibreHardwareMonitor with its "Remote Web Server" enabled, for CPU,
  fans and drives. Windows only exposes these sensors to programs that ship
  their own driver.
- Linux: `psutil.sensors_temperatures()` and `sensors_fans()` (hwmon).
- macOS: no public, permission-free API for temperatures, so the CPU temperature
  comes from a free command-line tool if the user installed one (smctemp, macmon
  or osx-cpu-temp). `powermetrics` is skipped on purpose: it needs sudo.
"""

from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from typing import TYPE_CHECKING, Any, Iterable, Iterator, Mapping, Optional

import psutil

from .hwinfo import short_gpu_name
from .shapes import Json

if TYPE_CHECKING:
    from psutil._ntuples import shwtemp

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_NUMBER = re.compile(r"-?\d+(?:[.,]\d+)?")
_RATE_UNITS = {"B/s": 1, "KB/s": 1024, "MB/s": 1024 ** 2, "GB/s": 1024 ** 3}
_SIZE_UNITS = {"B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3}
MIB = 1024 * 1024


def _number(text: Optional[str]) -> Optional[float]:
    """'45,3 °C' -> 45.3; '[N/A]' -> None. LHM formats numbers in the Windows locale."""
    match = _NUMBER.search(text or "")
    return float(match.group().replace(",", ".")) if match else None


def _with_unit(text: Optional[str], units: Mapping[str, int]) -> Optional[float]:
    """'111,6 KB/s' -> bytes per second; '1924,0 MB' -> bytes."""
    value = _number(text)
    unit = (text or "").split()[-1] if text else ""
    return value * units.get(unit, 1) if value is not None else None


def _first(values: Mapping[str, Optional[float]], names: Iterable[str]) -> Optional[float]:
    """First non-empty value among `names`, in order of preference."""
    return next((values[n] for n in names if values.get(n) is not None), None)


class NvidiaGpu:
    QUERY = "name,utilization.gpu,temperature.gpu,memory.used,memory.total,power.draw,fan.speed,clocks.gr,clocks.mem"
    LIMIT_EVERY = 60  # seconds; the limit doesn't change, no need to ask every reading

    def __init__(self) -> None:
        self.exe = shutil.which("nvidia-smi")
        self._limit: Optional[int] = None
        self._limit_at: float = 0

    def temp_limit(self, temp: float) -> Optional[int]:
        """Where the card starts to slow down to cool itself (°C), from the card. Newer
        drivers report "T.Limit", the degrees left until then; older ones the slowdown temp."""
        if time.time() - self._limit_at < self.LIMIT_EVERY:
            return self._limit
        self._limit_at = time.time()
        assert self.exe is not None  # read() only asks when nvidia-smi was found
        try:
            result = subprocess.run([self.exe, "-q", "-d", "TEMPERATURE"], capture_output=True, text=True,
                                    timeout=5, creationflags=_NO_WINDOW)
            self._limit = parse_nvidia_limit(result.stdout, temp)
        except (OSError, subprocess.SubprocessError):
            self._limit = None
        return self._limit

    def read(self) -> Optional[Json]:
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
        name, util, raw_temp, raw_used, raw_total, power, fan, clock, mem_clock = fields
        used, total = _number(raw_used), _number(raw_total)
        temp = _number(raw_temp)
        return {
            "name": short_gpu_name(name),
            "percent": _number(util),
            "temp": temp,
            "temp_limit": self.temp_limit(temp) if temp is not None else None,
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

    def __init__(self, url: str = "http://localhost:8085/data.json") -> None:
        self.url = url
        self._down_until: float = 0
        self.hint: Optional[str] = None  # what the user should do while it doesn't answer

    def read(self) -> Optional[Json]:
        if time.time() < self._down_until:
            return None
        try:
            with urllib.request.urlopen(self.url, timeout=1) as resp:
                tree = json.load(resp)
        except (OSError, ValueError):
            self._down_until = time.time() + self.RETRY_AFTER
            self.hint = self._why_down()
            return None
        self.hint = None

        result: Json = {"cpu": None, "gpu": None, "fans": [], "drives": []}
        gpus: list[Json] = []
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
    def _hardware(cls, node: Json) -> Iterator[Json]:
        """Every component, including those nested in others (the motherboard's sensor chip)."""
        for child in node.get("Children", []):
            if "HardwareId" in child:
                yield child
            if "SensorId" not in child:
                yield from cls._hardware(child)

    @staticmethod
    def _raw_group(hardware: Json, name: str) -> dict[str, Any]:
        """Sensors of a group ("Temperatures", "Data"...), merging groups that share a name."""
        values: dict[str, Any] = {}
        for group in hardware.get("Children", []):
            if group.get("Text") == name and "HardwareId" not in group:
                values.update({s.get("Text"): s.get("Value") for s in group.get("Children", [])})
        return values

    @classmethod
    def _group(cls, hardware: Json, name: str) -> dict[str, Optional[float]]:
        return {k: _number(v) for k, v in cls._raw_group(hardware, name).items()}

    def _cpu(self, hardware: Json) -> Json:
        temps = self._group(hardware, "Temperatures")
        temp = _first(temps, self.CPU_TEMP_NAMES)
        if temp is None:
            temp = max((t for t in temps.values() if t is not None), default=None)
        clocks = self._group(hardware, "Clocks")
        cores = [v for k, v in clocks.items() if k.startswith("Core #") and "Effective" not in k and v]
        average = clocks.get("Cores (Average)") or (sum(cores) / len(cores) if cores else None)
        # Intel reports how far each core is from TjMax, its throttling point: core + distance.
        limit = next((temps[name[:-len(" Distance to TjMax")]] + value  # type: ignore[operator]  # checked below
                      for name, value in temps.items()
                      if name.endswith(" Distance to TjMax") and value is not None
                      and temps.get(name[:-len(" Distance to TjMax")]) is not None), None)
        return {
            "temp": temp,
            "limit": round(limit) if limit else None,
            "power": self._group(hardware, "Powers").get("Package"),
            "clock": average,
            "clock_max": max(cores) if cores else None,
        }

    def _gpu(self, hardware: Json) -> Json:
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

    def _drive(self, hardware: Json) -> Json:
        temps = self._group(hardware, "Temperatures")
        rates = self._raw_group(hardware, "Throughput")
        return {
            "name": hardware.get("Text"),
            "temp": _first(temps, self.DRIVE_TEMP_NAMES),
            "temp_limit": temps.get("Warning Temperature"),  # the SSD's own (NVMe)
            "read": _with_unit(rates.get("Read Rate"), _RATE_UNITS),
            "write": _with_unit(rates.get("Write Rate"), _RATE_UNITS),
        }

    def _fans(self, hardware: Json, gpu: bool) -> list[Json]:
        rpms = self._group(hardware, "Fans")
        percents = self._group(hardware, "Controls")
        fans: list[Json] = []
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

    @staticmethod
    def _why_down() -> str:
        # Open but silent usually means its web server is off (it isn't always remembered).
        for proc in psutil.process_iter(["name"]):
            if (proc.info["name"] or "").lower().startswith("librehardwaremonitor"):
                return "turn on LibreHardwareMonitor's web server"
        return "open LibreHardwareMonitor"


def _read_file(path: str, scale: float = 1.0) -> Optional[float]:
    """Number from a sysfs file (None if it does not exist)."""
    try:
        with open(path, encoding="utf-8") as f:
            return float(f.read().strip()) / scale
    except (OSError, ValueError):
        return None


def _current_dpm_clock(path: str) -> Optional[float]:
    """Active clock from pp_dpm_sclk/pp_dpm_mclk: the line marked with '*' ('1: 2100Mhz *')."""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.rstrip().endswith("*"):
                    return _number(line.split(":", 1)[1])
    except OSError:
        pass
    return None


def linux_amd_gpu(drm: str = "/sys/class/drm") -> Optional[Json]:
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


def linux_cpu_sensor() -> Optional[shwtemp]:
    # psutil only has it on Linux (tests stand it in on other systems).
    temps: dict[str, list[shwtemp]] = psutil.sensors_temperatures()  # type: ignore[attr-defined, unused-ignore]
    for chip, labels in (("k10temp", ("Tctl", "Tdie")), ("zenpower", ("Tdie",)),
                         ("coretemp", ("Package id 0",)), ("cpu_thermal", ("",))):
        for sensor in temps.get(chip, []):
            if sensor.label in labels:
                return sensor
    return None


def linux_cpu_temp() -> Optional[float]:
    sensor = linux_cpu_sensor()
    return sensor.current if sensor else None


def linux_cpu_limit() -> Optional[float]:
    """hwmon's own limit for the CPU sensor ("high", else a bit under "critical")."""
    sensor = linux_cpu_sensor()
    if not sensor:
        return None
    if sensor.high and sensor.high > 40:
        return sensor.high
    return sensor.critical - 5 if sensor.critical and sensor.critical > 45 else None


def linux_fans() -> list[Json]:
    fans: list[Json] = []
    for chip, entries in (psutil.sensors_fans() or {}).items():  # type: ignore[attr-defined, unused-ignore]
        if chip == "amdgpu":  # shown as the GPU fan instead
            continue
        for i, fan in enumerate(entries):
            if fan.current:
                fans.append({"name": fan.label or f"{chip} {i + 1}", "rpm": fan.current, "percent": None, "gpu": False})
    return fans

class MacCpuTemp:
    """CPU temperature on macOS from the first optional tool that answers.

    smctemp reads the SMC on Intel and Apple Silicon; macmon covers Apple Silicon;
    osx-cpu-temp covers Intel (it prints 0.0 on Apple Silicon). None needs sudo.
    """

    COMMANDS: tuple[tuple[str, list[str]], ...] = (
        ("smctemp", ["-c", "-i25", "-n3"]),  # '64.2'; short interval and a few retries instead of 1 s
        ("macmon", ["pipe", "-s", "1", "-i", "200"]),  # one JSON line: {"temp": {"cpu_temp_avg": 43.7}}
        ("osx-cpu-temp", []),  # '61.8 °C'
    )

    RETRY_AFTER = 30  # none answered (e.g. osx-cpu-temp on Apple Silicon): don't spawn them every refresh

    def __init__(self) -> None:
        self.tools = [(name, shutil.which(name), args) for name, args in self.COMMANDS if shutil.which(name)]
        self._down_until: float = 0

    def read(self) -> Optional[float]:
        if not self.tools or time.time() < self._down_until:
            return None
        for name, path, args in self.tools:
            assert path is not None  # only tools that were found are kept
            try:
                result = subprocess.run([path] + args, capture_output=True, text=True, timeout=3)
            except (OSError, subprocess.SubprocessError, ValueError):
                continue
            if result.returncode == 0:
                temp = parse_mac_temp(name, result.stdout)
                if temp is not None:
                    return temp
        self._down_until = time.time() + self.RETRY_AFTER
        return None


def parse_mac_temp(tool: str, output: Optional[str]) -> Optional[float]:
    """Celsius from one of MacCpuTemp's tools, or None. 0 (or below) means the sensor was not read."""
    temp: Optional[float]
    if tool == "macmon":
        try:
            line = next(x for x in (output or "").splitlines() if x.strip().startswith("{"))
            temp = (json.loads(line).get("temp") or {}).get("cpu_temp_avg")
            temp = float(temp) if temp is not None else None
        except (StopIteration, ValueError, TypeError, AttributeError):
            return None
    else:
        temp = _number(output)
    return temp if temp is not None and 0 < temp < 150 else None


def parse_nvidia_limit(text: Optional[str], temp: Optional[float]) -> Optional[int]:
    """The slowdown point in `nvidia-smi -q -d TEMPERATURE` output, or None."""
    margin = re.search(r"GPU Current T\.Limit Temp\s*:\s*(-?[\d.]+)", text or "")
    if margin and temp is not None:
        return round(temp + float(margin.group(1)))
    for label in ("GPU Slowdown Temp", "GPU Max Operating Temp", "GPU Target Temperature"):
        match = re.search(re.escape(label) + r"\s*:\s*([\d.]+)\s*C", text or "")
        if match and float(match.group(1)) > 40:
            return round(float(match.group(1)))
    return None


# Where CPUs without a limit sensor throttle (AMD reports none). Checked in order; °C.
CPU_LIMITS = (
    (r"Ryzen \d+ 7\d{3}X3D", 89),
    (r"Ryzen \d+ 5\d{3}", 90),
    (r"Ryzen \d+ [79]\d{3}", 95),
    (r"Ryzen \d+ [1-3]\d{3}", 95),
    (r"Ryzen", 95),
    (r"Core|Intel", 100),
    (r"Apple M\d", 105),
)


def cpu_limit(name: Optional[str]) -> Optional[int]:
    """Fallback limit by CPU family, or None for an unknown CPU."""
    for pattern, limit in CPU_LIMITS:
        if re.search(pattern, name or ""):
            return limit
    return None


def lhm_url() -> str:
    """LibreHardwareMonitor's data URL, on the port set in its config (8085 by default)."""
    from . import lhm

    exe = lhm.find()
    return f"http://localhost:{lhm.port(exe) if exe else lhm.DEFAULT_PORT}/data.json"


class Sensors:
    """Combines the sources above and caches the result for a few seconds."""

    def __init__(self, refresh: float = 2) -> None:
        self.refresh = refresh
        self.nvidia = NvidiaGpu()
        self.lhm = LibreHardwareMonitor(lhm_url()) if sys.platform == "win32" else None
        self.mac_temp = MacCpuTemp() if sys.platform == "darwin" else None
        self._at: float = 0
        self._cache: Json = {"cpu_temp": None, "cpu_power": None, "cpu_clock": None, "cpu_clock_max": None,
                       "cpu_temp_limit": None, "gpu": None, "fans": [], "drives": [], "hint": None}

    def read(self) -> Json:
        if time.time() - self._at < self.refresh:
            return self._cache
        self._at = time.time()
        cpu: Json
        fans: list[Json]
        drives: list[Json]
        gpu: Optional[Json]
        cpu, fans, drives, gpu = {}, [], [], None
        hint = None
        if self.lhm:
            lhm = self.lhm.read()
            if lhm is None:  # CPU temperature, clocks and fans need it on Windows
                hint = self.lhm.hint or "open LibreHardwareMonitor"
            lhm = lhm or {}
            cpu, fans, drives, gpu = lhm.get("cpu") or {}, lhm.get("fans", []), lhm.get("drives", []), lhm.get("gpu")
        elif sys.platform.startswith("linux"):
            freq = psutil.cpu_freq()
            cpu = {"temp": linux_cpu_temp(), "limit": linux_cpu_limit(), "clock": freq.current if freq else None}
            fans = linux_fans()
            gpu = linux_amd_gpu()
        elif self.mac_temp:
            cpu = {"temp": self.mac_temp.read()}

        # nvidia-smi is the most reliable source for NVIDIA cards, so it wins when present.
        gpu = self.nvidia.read() or gpu
        if gpu and not any(f["gpu"] for f in fans) and (gpu.get("fan") is not None or gpu.get("fan_rpm")):
            fans.append({"name": "GPU", "rpm": gpu.get("fan_rpm"), "percent": gpu.get("fan"), "gpu": True})
        self._cache = {
            "cpu_temp": cpu.get("temp"),
            "cpu_power": cpu.get("power"),
            "cpu_clock": cpu.get("clock"),
            "cpu_clock_max": cpu.get("clock_max"),
            "cpu_temp_limit": cpu.get("limit"),
            "gpu": gpu,
            "fans": fans,
            "drives": drives,
            "hint": hint,
        }
        return self._cache
