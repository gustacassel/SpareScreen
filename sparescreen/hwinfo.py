"""Short hardware names (read once, when the agent starts)."""

from __future__ import annotations

import json
import platform
import re
import subprocess
import sys

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# SMBIOS memory type codes (Win32_PhysicalMemory.SMBIOSMemoryType)
_MEMORY_TYPES = {24: "DDR3", 26: "DDR4", 29: "LPDDR3", 30: "LPDDR4", 34: "DDR5", 35: "LPDDR5"}


def short_cpu_name(raw: str) -> str:
    """'AMD Ryzen 5 7600X 6-Core Processor' -> 'Ryzen 5 7600X';
    '13th Gen Intel(R) Core(TM) i7-13700K' -> 'Core i7-13700K'."""
    name = re.sub(r"\((R|TM|tm)\)", "", raw)
    name = re.sub(r"\s+\d+-Core Processor|\s+CPU\s*@.*|\s+Processor|\b\d+th Gen\b|\bAMD\b|\bIntel\b", "", name)
    return " ".join(name.split())


def cpu_name() -> str:
    try:
        if sys.platform == "win32":
            import winreg

            path = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
                raw = winreg.QueryValueEx(key, "ProcessorNameString")[0]
        elif sys.platform == "darwin":
            raw = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"],
                                 capture_output=True, text=True, timeout=5).stdout
        else:
            with open("/proc/cpuinfo", encoding="utf-8") as f:
                raw = next(line.split(":", 1)[1] for line in f if line.startswith("model name"))
    except Exception:
        raw = platform.processor()
    return short_cpu_name(raw or "")


def short_gpu_name(raw: str) -> str:
    """'NVIDIA GeForce RTX 5060' -> 'RTX 5060'; 'AMD Radeon RX 7800 XT' -> 'Radeon RX 7800 XT';
    'Intel(R) UHD Graphics 770' -> 'UHD Graphics 770'."""
    name = re.sub(r"\((R|TM|tm)\)|\bNVIDIA\b|\bGeForce\b|\bAMD\b|\bIntel\b", "", raw)
    return " ".join(name.split()) or raw


def ram_name(total_bytes: int) -> str:
    """'32 GB DDR5-6000' on Windows; just '32 GB' on other systems for now."""
    name = f"{round(total_bytes / 2**30)} GB"
    if sys.platform != "win32":
        return name
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_PhysicalMemory | Select-Object ConfiguredClockSpeed, SMBIOSMemoryType "
             "| ConvertTo-Json -Compress"],
            capture_output=True, text=True, timeout=15, creationflags=_NO_WINDOW,
        ).stdout
        modules = json.loads(out)
    except (OSError, ValueError, subprocess.SubprocessError):
        return name
    if isinstance(modules, dict):  # a single stick comes back as an object, not a list
        modules = [modules]
    kind = _MEMORY_TYPES.get(modules[0].get("SMBIOSMemoryType"), "")
    speed = max((m.get("ConfiguredClockSpeed") or 0) for m in modules)
    if kind:
        name += f" {kind}" + (f"-{speed}" if speed else "")
    return name
