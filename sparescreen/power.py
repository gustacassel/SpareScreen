"""The PC going to sleep: tell the phone before the connection drops.

While the PC sleeps the agent is frozen, so the phone only sees the data stop and would
show "Disconnected" all night. When the system announces the sleep, the agent sends one
last reading with `power.asleep` and the page shows a calm "PC asleep" screen instead;
over USB the phone's screen is also rested right away (screen.py), as if the PC were locked.

- Windows: PowerRegisterSuspendResumeNotification (Windows 8 and later) calls back just
  before sleeping and after waking.
- Linux: systemd-logind's PrepareForSleep signal, read with `gdbus monitor` when it's
  installed. Best effort: logind doesn't wait for us, so the notice may not always get out.
- macOS: not detected (it would need a native framework); the phone shows "Disconnected".

The flag clears itself on the first reading after waking (the clock has jumped), even if
the wake-up notice is missed or the sleep was cancelled.
"""

from __future__ import annotations

import atexit
import shutil
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Optional

from .shapes import Json

STALE = 30  # seconds: "asleep" set longer ago than this means we're awake again
GRACE = 2.0  # seconds the PC waits for the notice to go out before sleeping


class PowerWatch:
    name = "power"

    def __init__(self) -> None:
        self.asleep_at: Optional[float] = None
        self.on_sleep: Optional[Callable[[], None]] = None  # tells the phone (set by cli)
        self._keep: list[Any] = []  # the Windows callback must outlive the registration

    def asleep(self) -> bool:
        at = self.asleep_at
        if at is not None and time.time() - at > STALE:
            self.asleep_at = None
        return self.asleep_at is not None

    def read(self) -> Json:
        return {"asleep": self.asleep()}

    def going_to_sleep(self) -> None:
        self.asleep_at = time.time()
        if self.on_sleep:
            # On a thread with a time limit: a stuck phone (adb) must never hold up the sleep.
            worker = threading.Thread(target=self.on_sleep, name="power-sleep", daemon=True)
            worker.start()
            worker.join(GRACE)

    def woke_up(self) -> None:
        self.asleep_at = None

    def start(self) -> None:
        """Starts listening, where the system allows it. Never raises."""
        try:
            if sys.platform == "win32":
                self._start_windows()
            elif sys.platform.startswith("linux"):
                self._start_linux()
        except Exception as exc:  # no notice: the phone just shows "Disconnected"
            print(f"[power] can't watch for sleep: {exc}", flush=True)

    def _start_windows(self) -> None:
        if sys.platform != "win32":
            return  # lets type checkers on other OSes skip the rest
        import ctypes
        from ctypes import wintypes

        PBT_APMSUSPEND, PBT_APMRESUMESUSPEND, PBT_APMRESUMEAUTOMATIC = 4, 7, 18
        DEVICE_NOTIFY_CALLBACK = 2
        callback_type = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG, ctypes.c_void_p)

        class Params(ctypes.Structure):  # DEVICE_NOTIFY_SUBSCRIBE_PARAMETERS
            _fields_ = [("Callback", callback_type), ("Context", ctypes.c_void_p)]

        def notified(context: Any, kind: int, setting: Any) -> int:
            try:
                if kind == PBT_APMSUSPEND:
                    self.going_to_sleep()
                elif kind in (PBT_APMRESUMESUSPEND, PBT_APMRESUMEAUTOMATIC):
                    self.woke_up()
            except Exception:
                pass  # never let an error escape into Windows' callback
            return 0

        callback = callback_type(notified)
        params = Params(callback, None)
        handle = ctypes.c_void_p()
        error = ctypes.WinDLL("powrprof").PowerRegisterSuspendResumeNotification(
            DEVICE_NOTIFY_CALLBACK, ctypes.byref(params), ctypes.byref(handle))
        if error:
            raise OSError(error, "PowerRegisterSuspendResumeNotification failed")
        self._keep = [callback, params, handle]

    def _start_linux(self) -> None:
        gdbus = shutil.which("gdbus")
        if not gdbus:
            return
        process = subprocess.Popen(
            [gdbus, "monitor", "--system", "--dest", "org.freedesktop.login1",
             "--object-path", "/org/freedesktop/login1"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, text=True)

        def listen() -> None:
            assert process.stdout is not None  # stdout=PIPE above
            for line in process.stdout:
                # ".../login1: org.freedesktop.login1.Manager.PrepareForSleep (true,)"
                if "PrepareForSleep (true" in line:
                    self.going_to_sleep()
                elif "PrepareForSleep (false" in line:
                    self.woke_up()

        threading.Thread(target=listen, name="power", daemon=True).start()
        self._keep = [process]
        atexit.register(self.stop)

    def stop(self) -> None:
        """Ends `gdbus monitor`, which would otherwise outlive SpareScreen."""
        for item in self._keep:
            if isinstance(item, subprocess.Popen) and item.poll() is None:
                item.terminate()
