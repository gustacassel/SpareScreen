"""Command line: everything `sparescreen` (or `python -m sparescreen`) does."""

from __future__ import annotations

import argparse
import io
import os
import socket
import subprocess
import sys
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Optional, cast

from . import __version__, autostart, dev, screen, tray, update
from .appwindow import open_window
from .config import ConfigStore
from .demo import demo_sources
from .pairing import Pairing
from .panel import Panel
from .photos import Photos
from .power import PowerWatch
from .server import serve
from .sources import default_sources
from .shapes import Source
from .usb import PhoneSource, UsbBridge, find_adb

if TYPE_CHECKING:
    from .shapes import Activity


def lan_ip() -> str:
    """This machine's IP on the local network (the one the phone should use)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))  # sends nothing, just picks the interface
            ip: str = s.getsockname()[0]
            return ip
        except OSError:
            return "127.0.0.1"


LOG_FILE = Path.home() / ".sparescreen" / "sparescreen.log"


def log_to_file() -> None:
    """Without a console (--background, or the windowed executable), output goes to a log."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    log = open(LOG_FILE, "w", encoding="utf-8", errors="replace", buffering=1)
    sys.stdout = sys.stderr = log


def without(argv: list[str], *flags: str) -> list[str]:
    """argv minus the given flags (and the value right after the ones that take one)."""
    out: list[str] = []
    skip = False
    for arg in argv:
        if skip:
            skip = False
            continue
        name = arg.split("=", 1)[0]
        if name in flags:
            skip = "=" not in arg and name == "--autostart"
            continue
        out.append(arg)
    return out


def autostart_args() -> list[str]:
    """The options to start with at login: the ones given now, minus the one-off ones."""
    return without(sys.argv[1:], "--autostart", "--background", "--dev")


# Set on the windowless copy of the .exe: "greet" when the user double-clicked it.
DETACHED = "SPARESCREEN_DETACHED"


def console_is_ours() -> bool:
    """True when Windows opened this console just for us (the .exe was double-clicked),
    false when it belongs to a terminal the user typed the command in."""
    if sys.platform != "win32":
        return False  # only asked on Windows; this lets type checkers on other OSes skip the rest
    import ctypes

    import psutil

    pids = (ctypes.c_ulong * 32)()
    count = ctypes.windll.kernel32.GetConsoleProcessList(pids, 32)
    if not 0 < count <= 32:
        return False
    ours = {os.getpid()}
    try:
        parent = psutil.Process().parent()
        if parent and parent.exe() == sys.executable:  # PyInstaller's one-file launcher
            ours.add(parent.pid)
    except psutil.Error:
        pass
    return set(pids[:count]) <= ours


def detach(greet: bool) -> None:
    """Starts a copy of this .exe with no console window; the caller then exits, closing its own.

    Hiding the window instead doesn't work when Windows 11 opens console apps in
    Windows Terminal, so a fresh windowless process is the reliable way.
    """
    args = [sys.executable] + sys.argv[1:]
    if "--background" not in args:
        args.append("--background")
    # PYINSTALLER_RESET_ENVIRONMENT: the copy unpacks its own files instead of using
    # this process's temporary folder, which is deleted when this one exits.
    env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1", **{DETACHED: "greet" if greet else "quiet"})
    # Windows-only constants, read by name so type checkers on other OSes accept them.
    flags = getattr(subprocess, "CREATE_NO_WINDOW") | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP")
    subprocess.Popen(args, env=env, close_fds=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, creationflags=flags)


def handle_autostart(action: str) -> None:
    if action == "on":
        command = autostart.enable(autostart_args())
        print("SpareScreen will start when you log in:")
        print("  " + " ".join(command))
    elif action == "off":
        autostart.disable()
        print("SpareScreen will no longer start when you log in.")
    else:
        current = autostart.status()
        print("Autostart is on:" if current else "Autostart is off.")
        if current:
            print("  " + current)


def main() -> Optional[int]:
    # The packaged executable has a single entry point, so the status line is a subcommand.
    if len(sys.argv) > 1 and sys.argv[1] == "statusline":
        from . import statusline

        sys.argv = [sys.argv[0]] + sys.argv[2:]
        return statusline.main()

    frozen = getattr(sys, "frozen", False)
    parser = argparse.ArgumentParser(prog="sparescreen", description="SpareScreen: an old phone as a PC dashboard.")
    parser.add_argument("--version", action="version", version=f"SpareScreen {__version__}")
    parser.add_argument("--host", default="0.0.0.0", help="listen address (default: all interfaces)")
    parser.add_argument("--port", type=int, default=8765, help="HTTP port (default: 8765)")
    parser.add_argument("--interval", type=float, default=1.0, help="seconds between readings (default: 1)")
    usb = parser.add_argument_group("USB")
    usb.add_argument("--no-usb", action="store_true", help="do not look for phones on USB")
    usb.add_argument("--adb", help="path to adb, if it is not on the PATH")
    usb.add_argument("--no-open", action="store_true", help="do not open the page on the phone when it connects")
    usb.add_argument("--stay-awake", action="store_true",
                     help="turn on the phone's keep-screen-on option while it is on USB")
    parser.add_argument("--dev", action="store_true",
                        help="dev mode: restart when the code changes and reload the page")
    pairing_options = parser.add_argument_group("pairing")
    pairing_options.add_argument("--no-pairing", action="store_true",
                         help="let any device on the network see the data without a code (trusted networks only)")
    pairing_options.add_argument("--reset-pairing", action="store_true",
                         help="forget every paired device before starting")
    parser.add_argument("--demo", action="store_true",
                        help="show made-up data instead of this PC's (for screenshots and trying it out)")
    start = parser.add_argument_group("starting with the PC")
    start.add_argument("--autostart", choices=("on", "off", "status"),
                       help="start SpareScreen when you log in (keeps the other options you pass)")
    start.add_argument("--background", action="store_true",
                       help=f"run without a window, with a tray icon where possible; output goes to {LOG_FILE}")
    start.add_argument("--no-tray", action="store_true", help="no tray icon in --background mode")
    args = parser.parse_args()

    # The .exe is a console app, so typed in a terminal it prints the address and code
    # there. Double-clicked (or started at login) it would leave a black window open:
    # run a windowless copy in the tray instead and close this one.
    detached = os.environ.get(DETACHED)
    if frozen and sys.platform == "win32" and not detached and not args.autostart:
        if args.background or console_is_ours():
            detach(greet=not args.background)
            return 0
    greet = detached == "greet"  # double-clicked: open the page and say where the icon is

    if args.background or sys.stdout is None:
        log_to_file()
    else:
        # When output goes to a file/pipe, Windows would use cp1252 and mangle non-ASCII characters.
        cast(io.TextIOWrapper, sys.stdout).reconfigure(encoding="utf-8", errors="replace")

    if args.autostart:
        handle_autostart(args.autostart)
        return None

    if args.dev and not dev.is_child():
        dev.supervise(sys.argv[1:])
        return None

    # The demo keeps its own settings and paired devices: trying it out never touches yours.
    demo_dir = Path.home() / ".sparescreen" / "demo"
    config = ConfigStore(demo_dir / "config.json") if args.demo else ConfigStore()
    adb = None if args.no_usb else find_adb(args.adb)
    power = PowerWatch()
    bridge = None
    if adb:
        open_page = not args.no_open and not dev.is_restart()
        # The PC going to sleep counts as locked: a USB phone's screen rests too.
        bridge = UsbBridge(adb, args.port, open_page=open_page, stay_awake=args.stay_awake,
                           screen=lambda: screen.wanted(config, locked=True if power.asleep() else None))
    if args.demo:
        sources: list[Source] = demo_sources() + [config]
    else:
        sources = default_sources(config) + [PhoneSource(bridge), config]
    updater = update.Updater(config)
    photos = Photos(config.photos_dir)
    sources += [updater, power, photos]
    if args.dev:
        sources.append(dev.DevSource())
    if args.no_pairing:
        pairing = None
    else:
        pairing = Pairing(demo_dir / "devices.json") if args.demo else Pairing()
    if pairing and args.reset_pairing:
        pairing.reset()
    phone_url = f"http://{lan_ip()}:{args.port}" if args.host in ("0.0.0.0", "::") else None
    local_url = f"http://localhost:{args.port}"
    window_url = f"{local_url}/panel.html"  # the PC window: checks, devices, pairing
    info = {"phone_url": phone_url, "version": __version__}
    activity = cast("Optional[Activity]", next((s for s in sources if s.name == "activity"), None))
    panel = Panel(pairing, bridge, usb=not args.no_usb, info=info, local_url=local_url,
                  autostart_args=autostart_args(), config=config, activity=activity, updater=updater,
                  photos=photos)
    try:
        server = serve(args.host, args.port, sources, args.interval, config, pairing, info=info, panel=panel)
    except OSError as exc:
        print(f"Can't use port {args.port} ({exc}). Is SpareScreen already running? "
              f"Open {window_url}, or pick another port with --port.", flush=True)
        if frozen and (greet or not args.background):
            open_window(window_url)  # double-clicked again: show the one that is running
        return 1
    updater.quit = server.shutdown  # an update stops SpareScreen, then relaunch() below starts the new one
    updater.clean_up()
    updater.start()

    def before_sleep() -> None:
        """The PC is about to sleep: one last reading tells the phone, and a USB phone's screen rests."""
        if panel.hub:
            panel.hub.publish(dict(panel.hub.snapshot, power=power.read()))
        if bridge:
            bridge.rest_screens()
        time.sleep(0.5)  # a moment for that reading to reach the phone

    power.on_sleep = before_sleep
    power.start()
    print(f"SpareScreen running on port {args.port}." + (" Demo mode: showing made-up data." if args.demo else ""))
    if phone_url:
        print(f"  Wi-Fi: on your phone, open {phone_url}")
        if pairing:
            print(f"         pairing code for new devices: {pairing.code}")

    if bridge:
        print("  USB:   plug the phone in (with USB debugging on) and the page opens by itself.")
        bridge.start()
    elif not args.no_usb:
        print("  USB:   adb not found. Install Android Platform Tools to use the cable (see the README).")
    print(f"  On this PC: {local_url} (dashboard) and {window_url} (checks, devices, pairing)")
    if frozen and (greet or not args.background):
        open_window(window_url)  # the packaged app has no terminal to read: show the PC window
    if args.background and not args.no_tray and tray.available():
        print("Tray icon on; quit from its menu.", flush=True)
        try:
            tray.run(server, local_url, window_url, phone_url, pairing, autostart_args(), greet=greet)
        finally:
            shut_down(server, bridge, power)
        if updater.relaunch_wanted:
            update.relaunch({DETACHED: "quiet"})
        return None
    print("Press Ctrl+C to quit.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        shut_down(server, bridge, power)
    if updater.relaunch_wanted:
        print("Updated: starting the new version...", flush=True)
        update.relaunch({DETACHED: "quiet"})
    return None


def shut_down(server: ThreadingHTTPServer, bridge: Optional[UsbBridge], power: PowerWatch) -> None:
    server.server_close()
    power.stop()
    if bridge:
        bridge.restore()  # a dimmed or sleeping phone screen goes back to how it was
