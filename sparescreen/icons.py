"""Icon of a program, as PNG bytes (used for game and player icons).

Windows: the icon embedded in the .exe at 256 px (PrivateExtractIcons, falling back
to the small associated icon), turned into PNG by PowerShell's System.Drawing (part of
Windows, no extra dependency). Other systems: None for now, the page
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

SIZE = 256  # big enough to fill the game screen when there's no store art

_EXTRACT = (
    "Add-Type -AssemblyName System.Drawing;"
    "Add-Type -TypeDefinition 'using System;using System.Runtime.InteropServices;"
    "public static class SpareScreenIcon{[DllImport(\"user32.dll\",CharSet=CharSet.Unicode)]"
    "public static extern uint PrivateExtractIcons(string f,int i,int cx,int cy,IntPtr[] h,int[] id,uint n,uint fl);}';"
    "$h=New-Object IntPtr[] 1;$id=New-Object int[] 1;"
    f"$n=[SpareScreenIcon]::PrivateExtractIcons($env:SPARESCREEN_EXE,0,{SIZE},{SIZE},$h,$id,1,0);"
    "if($n -gt 0 -and $h[0] -ne [IntPtr]::Zero){$b=[System.Drawing.Icon]::FromHandle($h[0]).ToBitmap()}"
    "else{$b=[System.Drawing.Icon]::ExtractAssociatedIcon($env:SPARESCREEN_EXE).ToBitmap()};"
    "$m=New-Object System.IO.MemoryStream;"
    "$b.Save($m,[System.Drawing.Imaging.ImageFormat]::Png);"
    "[Convert]::ToBase64String($m.ToArray())"
)


# A window's own icon (WM_GETICON, else its class icon). Games that run inside another
# program (Minecraft in javaw.exe) set their icon on the window, not in the exe.
_WINDOW = (
    "Add-Type -AssemblyName System.Drawing;"
    "Add-Type -TypeDefinition 'using System;using System.Runtime.InteropServices;"
    "public static class SpareScreenWindowIcon{"
    "[DllImport(\"user32.dll\")]public static extern IntPtr SendMessageTimeout(IntPtr h,uint m,IntPtr w,IntPtr l,"
    "uint f,uint t,out IntPtr r);"
    "[DllImport(\"user32.dll\",EntryPoint=\"GetClassLongPtrW\")]public static extern IntPtr GetClassLongPtr(IntPtr h,int i);}';"
    "$w=[IntPtr][long]$env:SPARESCREEN_HWND;$i=[IntPtr]::Zero;"
    "[void][SpareScreenWindowIcon]::SendMessageTimeout($w,0x7F,[IntPtr]1,[IntPtr]0,2,500,[ref]$i);"  # ICON_BIG
    "if($i -eq [IntPtr]::Zero){$i=[SpareScreenWindowIcon]::GetClassLongPtr($w,-14)};"  # GCLP_HICON
    "if($i -eq [IntPtr]::Zero){exit 1};"
    "$m=New-Object System.IO.MemoryStream;"
    "[System.Drawing.Icon]::FromHandle($i).ToBitmap().Save($m,[System.Drawing.Imaging.ImageFormat]::Png);"
    "[Convert]::ToBase64String($m.ToArray())"
)


def _run(script, env, key):
    if sys.platform != "win32":
        return None
    with _lock:
        if key in _cache:
            return _cache[key]
    data = None
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=10, creationflags=_NO_WINDOW,
            # Values go in environment variables, so no quoting can break the command.
            env=dict(os.environ, **env),
        )
        if result.returncode == 0 and result.stdout.strip():
            data = base64.b64decode(result.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        data = None
    with _lock:
        _cache[key] = data
    return data


def exe_icon_png(path):
    """PNG bytes of the program's icon, or None."""
    return _run(_EXTRACT, {"SPARESCREEN_EXE": str(path)}, path) if path else None


def window_icon_png(hwnd):
    """PNG bytes of a window's icon, or None."""
    return _run(_WINDOW, {"SPARESCREEN_HWND": str(int(hwnd))}, ("window", int(hwnd))) if hwnd else None
