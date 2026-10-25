"""Icon of a program, as PNG bytes (used for game and player icons).

Windows: the icon embedded in the .exe, extracted by PowerShell's System.Drawing
(part of Windows, no extra dependency). Other systems: None for now, the page
just doesn't show an icon. Results are cached per file, including failures.
"""

import base64
import os
import subprocess
import sys
import threading

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_cache = {}
_lock = threading.Lock()

_EXTRACT = (
    "Add-Type -AssemblyName System.Drawing;"
    "$i=[System.Drawing.Icon]::ExtractAssociatedIcon($env:SPARESCREEN_EXE);"
    "$m=New-Object System.IO.MemoryStream;"
    "$i.ToBitmap().Save($m,[System.Drawing.Imaging.ImageFormat]::Png);"
    "[Convert]::ToBase64String($m.ToArray())"
)


def exe_icon_png(path):
    """PNG bytes of the program's icon, or None."""
    if not path or sys.platform != "win32":
        return None
    with _lock:
        if path in _cache:
            return _cache[path]
    data = None
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", _EXTRACT],
            capture_output=True, text=True, timeout=10, creationflags=_NO_WINDOW,
            # The path goes in an environment variable, so no quoting can break the command.
            env=dict(os.environ, SPARESCREEN_EXE=str(path)),
        )
        if result.returncode == 0 and result.stdout.strip():
            data = base64.b64decode(result.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        data = None
    with _lock:
        _cache[path] = data
    return data
