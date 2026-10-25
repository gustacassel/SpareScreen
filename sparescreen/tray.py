"""Tray icon (next to the clock on Windows) while SpareScreen runs in the background.

The menu opens the PC window and the dashboard, shows the phone address and pairing code, turns
"start when you log in" on and off, and quits. It uses pystray, installed with
SpareScreen on Windows; on Linux and macOS it's used when installed
(`pip install pystray pillow`) and the desktop shows tray icons. Without it,
SpareScreen just runs in the background as before.
"""

import sys
import threading
import webbrowser
from pathlib import Path

from . import autostart
from .appwindow import open_window

ICON = Path(__file__).parent / "web" / "icon-180.png"


def available():
    try:
        import pystray  # noqa: F401  (on Linux this also needs a display to load)
        from PIL import Image  # noqa: F401
    except Exception:
        return False
    return True


def start_label(platform=None):
    return "Start with Windows" if (platform or sys.platform) == "win32" else "Start when I log in"


def entries(local_url, window_url, phone_url, pairing, autostart_args):
    """The menu as plain data: (label or callable, action or None, options). Kept apart to test it."""
    items = [("Open SpareScreen", lambda: open_window(window_url), {"default": True}),
             ("Open dashboard", lambda: webbrowser.open(local_url), {})]
    if phone_url:
        items.append((f"Phone: {phone_url}", None, {}))
    if pairing:
        items.append((lambda: f"Pairing code: {pairing.code}", None, {}))  # the code can change

    def toggle():
        if autostart.status():
            autostart.disable()
        else:
            autostart.enable(autostart_args)

    items.append(("-", None, {}))
    items.append((start_label(), toggle, {"checked": lambda: bool(autostart.status())}))
    items.append(("Quit", "quit", {}))
    return items


def run(server, local_url, window_url, phone_url, pairing, autostart_args, greet=False):
    """Serves from a thread and keeps the icon on the main thread (macOS requires it) until Quit."""
    import pystray
    from PIL import Image

    threading.Thread(target=server.serve_forever, daemon=True).start()

    def menu_item(label, action, options):
        if label == "-":
            return pystray.Menu.SEPARATOR
        text = (lambda item: label()) if callable(label) else label
        if action == "quit":
            return pystray.MenuItem(text, lambda icon, item: icon.stop())
        checked = options.get("checked")
        return pystray.MenuItem(
            text,
            (lambda icon, item: action()) if action else None,
            checked=(lambda item: checked()) if checked else None,
            default=options.get("default", False),
            enabled=action is not None,
        )

    menu = pystray.Menu(*[menu_item(*entry)
                          for entry in entries(local_url, window_url, phone_url, pairing, autostart_args)])
    title = "SpareScreen" + (f" - {phone_url}" if phone_url else "")
    icon = pystray.Icon("sparescreen", Image.open(ICON), title, menu)

    def setup(icon):
        icon.visible = True
        if greet and getattr(icon, "HAS_NOTIFICATION", False):
            icon.notify("Running in the tray. Click the icon to open SpareScreen again.",
                        "SpareScreen")

    try:
        icon.run(setup=setup)
    finally:
        server.shutdown()
