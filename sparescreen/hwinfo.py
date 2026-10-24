"""Nomes curtos das peças (lidos uma vez, na partida do agente)."""

import json
import platform
import re
import subprocess
import sys

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Códigos SMBIOS de tipo de memória (Win32_PhysicalMemory.SMBIOSMemoryType)
_MEMORY_TYPES = {24: "DDR3", 26: "DDR4", 29: "LPDDR3", 30: "LPDDR4", 34: "DDR5", 35: "LPDDR5"}


def short_cpu_name(raw):
    """'AMD Ryzen 5 7600X 6-Core Processor' -> 'Ryzen 5 7600X';
    '13th Gen Intel(R) Core(TM) i7-13700K' -> 'Core i7-13700K'."""
    name = re.sub(r"\((R|TM|tm)\)", "", raw)
    name = re.sub(r"\s+\d+-Core Processor|\s+CPU\s*@.*|\s+Processor|\b\d+th Gen\b|\bAMD\b|\bIntel\b", "", name)
    return " ".join(name.split())


def cpu_name():
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


def short_gpu_name(raw):
    """'NVIDIA GeForce RTX 5060' -> 'RTX 5060'."""
    return " ".join(raw.replace("NVIDIA", "").replace("GeForce", "").split())


def ram_name(total_bytes):
    """'32 GB DDR5-6000' no Windows; só '32 GB' nos outros sistemas por enquanto."""
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
    if isinstance(modules, dict):  # um pente só vem como objeto, não lista
        modules = [modules]
    kind = _MEMORY_TYPES.get(modules[0].get("SMBIOSMemoryType"), "")
    speed = max((m.get("ConfiguredClockSpeed") or 0) for m in modules)
    if kind:
        name += f" {kind}" + (f"-{speed}" if speed else "")
    return name
