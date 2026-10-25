"""Names the phone may reach this PC by, instead of its IP (which the router can change).

- `name.local`: mDNS, answered by the PC itself (Windows 10+, macOS, Linux with Avahi).
  iPhones resolve it; Android only from version 12.
- `name`: many home routers put each PC's name in their DNS.
- the full name (`name.lan`, `name.home`...) when the system knows the router's suffix.

None of them is guaranteed, and only the phone knows what it can resolve, so the page
tests them from the phone (GET /whoami on each) and moves to the first one that answers.
"""

import re
import secrets
import socket
import threading

# Answered by /whoami, so the page knows a name reached *this* agent and not some other machine.
INSTANCE = secrets.token_hex(8)

_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


def _valid(name):
    return bool(name) and len(name) <= 253 and all(_LABEL.match(part) for part in name.split("."))


_this_pc = None  # this PC's list, once warm_up() has looked up the full name


def warm_up():
    """Looks up this PC's full name in the background: getfqdn() can take many seconds
    (reverse DNS, slow on macOS), and the page asks for the names right away."""
    def look_up():
        global _this_pc
        _this_pc = candidates(socket.gethostname(), socket.getfqdn())

    threading.Thread(target=look_up, name="names", daemon=True).start()


def candidates(hostname=None, fqdn=None):
    """['desktop.local', 'desktop', 'desktop.lan'] for this PC, best first, only valid DNS names."""
    if hostname is None and fqdn is None:
        if _this_pc is not None:
            return list(_this_pc)
        hostname, fqdn = socket.gethostname(), ""  # full name not looked up yet
    hostname = hostname.strip().lower()
    fqdn = fqdn.strip().lower().rstrip(".")
    short = hostname.split(".")[0]
    names = []
    for name in (f"{short}.local", short, fqdn if fqdn != short else ""):
        if name and _valid(name) and name not in names and not name.endswith(".localdomain"):
            names.append(name)
    return names
