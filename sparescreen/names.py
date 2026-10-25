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

# Answered by /whoami, so the page knows a name reached *this* agent and not some other machine.
INSTANCE = secrets.token_hex(8)

_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


def _valid(name):
    return bool(name) and len(name) <= 253 and all(_LABEL.match(part) for part in name.split("."))


def candidates(hostname=None, fqdn=None):
    """['desktop.local', 'desktop', 'desktop.lan'] for this PC, best first, only valid DNS names."""
    hostname = (hostname if hostname is not None else socket.gethostname()).strip().lower()
    fqdn = (fqdn if fqdn is not None else socket.getfqdn()).strip().lower().rstrip(".")
    short = hostname.split(".")[0]
    names = []
    for name in (f"{short}.local", short, fqdn if fqdn != short else ""):
        if name and _valid(name) and name not in names and not name.endswith(".localdomain"):
            names.append(name)
    return names
