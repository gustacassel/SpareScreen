"""Entry point: python -m sparescreen"""

import argparse
import socket
import sys

from . import dev
from .config import ConfigStore
from .server import serve
from .sources import default_sources
from .usb import UsbBridge, find_adb


def lan_ip():
    """This machine's IP on the local network (the one the phone should use)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))  # sends nothing, just picks the interface
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def main():
    parser = argparse.ArgumentParser(prog="sparescreen", description="SpareScreen: an old phone as a PC dashboard.")
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
    args = parser.parse_args()

    # When output goes to a file/pipe, Windows would use cp1252 and mangle non-ASCII characters.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if args.dev and not dev.is_child():
        dev.supervise(sys.argv[1:])
        return

    config = ConfigStore()
    sources = default_sources() + [config]
    if args.dev:
        sources.append(dev.DevSource())
    server = serve(args.host, args.port, sources, args.interval, config)
    print(f"SpareScreen running on port {args.port}.")
    if args.host in ("0.0.0.0", "::"):
        print(f"  Wi-Fi: on your phone, open http://{lan_ip()}:{args.port}")

    if not args.no_usb:
        adb = find_adb(args.adb)
        if adb:
            print("  USB:   plug the phone in (with USB debugging on) and the page opens by itself.")
            open_page = not args.no_open and not dev.is_restart()
            UsbBridge(adb, args.port, open_page=open_page, stay_awake=args.stay_awake).start()
        else:
            print("  USB:   adb not found. Install Android Platform Tools to use the cable (see the README).")
    print("Press Ctrl+C to quit.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
