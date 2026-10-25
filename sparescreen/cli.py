"""Command line: everything `sparescreen` (or `python -m sparescreen`) does."""

import argparse
import socket
import sys
import webbrowser
from pathlib import Path

from . import __version__, autostart, dev
from .config import ConfigStore
from .demo import demo_sources
from .pairing import Pairing
from .server import serve
from .sources import default_sources
from .usb import PhoneSource, UsbBridge, find_adb


def lan_ip():
    """This machine's IP on the local network (the one the phone should use)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))  # sends nothing, just picks the interface
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


LOG_FILE = Path.home() / ".sparescreen" / "sparescreen.log"


def log_to_file():
    """Without a console (--background, or the windowed executable), output goes to a log."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    log = open(LOG_FILE, "w", encoding="utf-8", errors="replace", buffering=1)
    sys.stdout = sys.stderr = log


def without(argv, *flags):
    """argv minus the given flags (and the value right after the ones that take one)."""
    out, skip = [], False
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


def handle_autostart(action):
    if action == "on":
        command = autostart.enable(without(sys.argv[1:], "--autostart", "--background", "--dev"))
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


def main():
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
    pairing = parser.add_argument_group("pairing")
    pairing.add_argument("--no-pairing", action="store_true",
                         help="let any device on the network see the data without a code (trusted networks only)")
    pairing.add_argument("--reset-pairing", action="store_true",
                         help="forget every paired device before starting")
    parser.add_argument("--demo", action="store_true",
                        help="show made-up data instead of this PC's (for screenshots and trying it out)")
    start = parser.add_argument_group("starting with the PC")
    start.add_argument("--autostart", choices=("on", "off", "status"),
                       help="start SpareScreen when you log in (keeps the other options you pass)")
    start.add_argument("--background", action="store_true",
                       help=f"run without a window; output goes to {LOG_FILE}")
    args = parser.parse_args()

    if args.background and sys.platform == "win32" and frozen:
        # The packaged .exe is a console app (so double-clicking it shows the address and
        # code); when started at login, let go of that window right away.
        import ctypes

        ctypes.windll.kernel32.FreeConsole()
    if args.background or sys.stdout is None:
        log_to_file()
    else:
        # When output goes to a file/pipe, Windows would use cp1252 and mangle non-ASCII characters.
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if args.autostart:
        handle_autostart(args.autostart)
        return

    if args.dev and not dev.is_child():
        dev.supervise(sys.argv[1:])
        return

    config = ConfigStore()
    adb = None if args.no_usb else find_adb(args.adb)
    bridge = None
    if adb:
        open_page = not args.no_open and not dev.is_restart()
        bridge = UsbBridge(adb, args.port, open_page=open_page, stay_awake=args.stay_awake)
    if args.demo:
        sources = demo_sources() + [config]
    else:
        sources = default_sources(config) + [PhoneSource(bridge), config]
    if args.dev:
        sources.append(dev.DevSource())
    pairing = None if args.no_pairing else Pairing()
    if pairing and args.reset_pairing:
        pairing.reset()
    phone_url = f"http://{lan_ip()}:{args.port}" if args.host in ("0.0.0.0", "::") else None
    local_url = f"http://localhost:{args.port}"
    try:
        server = serve(args.host, args.port, sources, args.interval, config, pairing,
                       info={"phone_url": phone_url, "version": __version__})
    except OSError as exc:
        print(f"Can't use port {args.port} ({exc}). Is SpareScreen already running? "
              f"Open {local_url}, or pick another port with --port.", flush=True)
        if frozen and not args.background:
            webbrowser.open(local_url)  # double-clicked again: show the one that is running
        return 1
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
    print(f"  On this PC: {local_url} (address and pairing code are in its settings)")
    print("Press Ctrl+C to quit.", flush=True)
    if frozen and not args.background:
        webbrowser.open(local_url)  # the packaged app has no terminal to read: show the page
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
