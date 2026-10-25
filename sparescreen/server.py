"""HTTP server: serves the page and streams the data over Server-Sent Events."""

import itertools
import json
import mimetypes
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import images, names
from .pairing import LOCAL_ADDRESSES

WEB_DIR = Path(__file__).parent / "web"


class Hub:
    """Holds the latest snapshot and wakes the clients when a new one arrives."""

    def __init__(self):
        self._cond = threading.Condition()
        self._version = 0
        self._payload = None
        self.snapshot = {}  # the latest one, for the PC window's checks

    def publish(self, snapshot):
        payload = json.dumps(snapshot, separators=(",", ":"))
        with self._cond:
            self._version += 1
            self._payload = payload
            self.snapshot = snapshot
            self._cond.notify_all()

    def wait_next(self, last_version, timeout):
        with self._cond:
            self._cond.wait_for(lambda: self._version != last_version, timeout)
            return self._version, self._payload


class Clients:
    """Devices with the dashboard open right now (one entry per open data stream)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._open = {}

    def add(self, info):
        with self._lock:
            key = next(self._ids)
            self._open[key] = dict(info, since=time.time())
            return key

    def remove(self, key):
        with self._lock:
            self._open.pop(key, None)

    def list(self):
        with self._lock:
            return [dict(c) for c in self._open.values()]


LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]"}


def start_sampler(hub, sources, interval):
    def loop():
        while True:
            snapshot = {"time": time.time()}
            for source in sources:
                try:
                    snapshot[source.name] = source.read()
                except Exception as exc:  # one failing source does not take down the others
                    snapshot[source.name] = {"error": str(exc)}
            hub.publish(snapshot)
            time.sleep(interval)

    threading.Thread(target=loop, name="sampler", daemon=True).start()


def make_handler(hub, config, pairing, info, clients, panel):
    class Handler(BaseHTTPRequestHandler):
        def _trusted(self):
            return pairing is None or pairing.is_trusted(self.client_address[0], self.headers.get("Cookie"))

        def _local(self):
            """This PC, reached by its own name (a DNS-rebinding page would carry another Host)."""
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].lower()
            return self.client_address[0] in LOCAL_ADDRESSES and host in LOCAL_HOSTS

        def _cross_site(self):
            """A POST sent by another website's page: browsers always say where it comes from."""
            origin = self.headers.get("Origin")
            return bool(origin) and urlparse(origin).netloc.lower() != (self.headers.get("Host") or "").lower()

        def _send_json(self, status, data, headers=()):
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            for name, value in headers:
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self):
            size = min(int(self.headers.get("Content-Length") or 0), 10_000)
            return json.loads(self.rfile.read(size) or b"{}")

        def do_GET(self):
            path, _, query = self.path.partition("?")
            if path in ("/", "/index.html") and "handoff=" in query:
                self._redeem(parse_qs(query).get("handoff", [""])[0])
            elif path == "/whoami":
                # The page on the phone tries the PC's names; this says "yes, it's this agent".
                # No data at all, and readable from the page's other address (CORS).
                self._send_json(200, {"id": names.INSTANCE}, [("Access-Control-Allow-Origin", "*")])
            elif path == "/names":
                if self._trusted():
                    self._send_json(200, {"id": names.INSTANCE, "names": names.candidates(),
                                          "port": self.server.server_address[1]})
                else:
                    self._send_json(401, {})
            elif path == "/events":
                if self._trusted():
                    self._stream_events()
                else:
                    self.send_error(401)
            elif path == "/auth":
                trusted = self._trusted()
                if not trusted and pairing is not None:
                    pairing.note_waiting(self.client_address[0], self.headers.get("User-Agent") or "")
                self._send_json(200, {"paired": trusted, "pairing": pairing is not None})
            elif path == "/panel/state":
                if panel is None or not self._local():
                    self._send_json(403, {})
                else:
                    self._send_json(200, panel.state(clients.list()))
            elif path == "/panel/events":
                if panel is None or not self._local():
                    self.send_error(403)
                else:
                    self._stream_alive()
            elif path == "/pair-code":
                # Only this PC may read the code (the page on the PC can show it).
                local = pairing is not None and self.client_address[0] in LOCAL_ADDRESSES
                self._send_json(200 if local else 403, {"code": pairing.code} if local else {})
            elif path.startswith("/art/"):
                self._serve_art(path[len("/art/"):])
            elif path == "/info":
                # "Connect a phone" details for the settings screen, only on this PC.
                if self.client_address[0] not in LOCAL_ADDRESSES:
                    self._send_json(403, {})
                else:
                    self._send_json(200, dict(info or {}, code=pairing.code if pairing else None))
            else:
                self._serve_static("index.html" if path == "/" else path.lstrip("/"))

        def do_POST(self):
            path = self.path.split("?", 1)[0]
            try:
                data = self._read_json()
            except ValueError:
                self.send_error(400)
                return
            if self._cross_site():
                self.send_error(403)
            elif path == "/pair" and pairing is not None:
                self._pair(data)
            elif path == "/names/works" and isinstance(data, dict):
                if not self._trusted():
                    self.send_error(401)
                    return
                if panel is not None and data.get("name") in names.candidates():
                    panel.name_works(data["name"])
                self._send_json(200, {})
            elif path == "/handoff":
                # Moving to another address of this PC: a one-time code carries the pairing over.
                digest = None if pairing is None else pairing.paired_hash(self.headers.get("Cookie"))
                if not self._trusted():
                    self.send_error(401)
                    return
                self._send_json(200, {"code": pairing.handoff(digest) if digest else None})
            elif path == "/panel/action" and panel is not None:
                if not self._local() or not isinstance(data, dict):
                    self.send_error(403)
                    return
                self._send_json(200, panel.act(str(data.get("action", "")), data))
            elif path == "/config" and config is not None:
                if not self._trusted():
                    self.send_error(401)
                    return
                self._send_json(200, config.update(data))
            else:
                self.send_error(404)

        def _pair(self, data):
            code = data.get("code", "") if isinstance(data, dict) else ""
            token, error = pairing.pair(code, self.headers.get("User-Agent") or "", self.client_address[0])
            if token:
                self._send_json(200, {"paired": True}, [("Set-Cookie", pairing.cookie_header(token))])
            elif error[0] == "locked":
                self._send_json(429, {"error": "locked", "retry_in": error[1]})
            else:
                self._send_json(403, {"error": "wrong", "attempts_left": error[1]})

        def _redeem(self, code):
            """Arriving at a new address with a handoff code: set this address's cookie."""
            token = pairing.redeem(code, self.client_address[0]) if pairing is not None and code else None
            self.send_response(302)
            self.send_header("Location", "/")
            if token:
                self.send_header("Set-Cookie", pairing.cookie_header(token))
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _serve_art(self, key):
            # Covers and icons reveal what you're playing, so they need pairing like the data.
            item = images.get(key) if self._trusted() else None
            if not item:
                self.send_error(404 if self._trusted() else 401)
                return
            data, ctype = item
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "private, max-age=86400")  # the URL changes with the image
            self.end_headers()
            self.wfile.write(data)

        def _serve_static(self, name):
            file = (WEB_DIR / name).resolve()
            if file.parent != WEB_DIR.resolve() or not file.is_file():
                self.send_error(404)
                return
            body = file.read_bytes()
            ctype = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype.endswith("javascript"):
                ctype += "; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)

        def _stream_alive(self):
            """An open stream that only says "still here": the PC window closes itself when
            it drops, so quitting SpareScreen from the tray also closes the window."""
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            try:
                while True:
                    self.wfile.write(b": alive\n\n")
                    self.wfile.flush()
                    time.sleep(15)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def _stream_events(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            address = self.client_address[0]
            local = address in LOCAL_ADDRESSES
            # Remote devices are tied to their pairing: unpaired (or replaced by a new device)
            # means the stream closes, and the page asks for the code again.
            digest = None if local or pairing is None else pairing.paired_hash(self.headers.get("Cookie"))
            key = clients.add({"address": address, "local": local, "agent": self.headers.get("User-Agent") or ""})
            version = 0
            try:
                while True:
                    if digest and not pairing.knows(digest):
                        break
                    new_version, payload = hub.wait_next(version, timeout=15)
                    if new_version == version or payload is None:
                        self.wfile.write(b": ping\n\n")
                    else:
                        version = new_version
                        self.wfile.write(f"data: {payload}\n\n".encode())
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass  # the phone closed the page or lost the connection
            finally:
                clients.remove(key)

        def log_message(self, fmt, *args):
            if "/events" not in self.path:
                super().log_message(fmt, *args)

    return Handler


def serve(host, port, sources, interval, config=None, pairing=None, info=None, panel=None):
    """`config` (ConfigStore) receives the changes made on the settings screen.
    `pairing` (Pairing), when given, restricts the data to paired devices.
    `info` ({"phone_url", "version"}) is shown on this PC's settings screen.
    `panel` (panel.Panel) answers the PC window, on this machine only."""
    hub = Hub()
    clients = Clients()
    if panel is not None:
        panel.hub = hub
    server = ThreadingHTTPServer((host, port), make_handler(hub, config, pairing, info, clients, panel))
    start_sampler(hub, sources, interval)  # only once the port is ours (a busy port fails above)
    names.warm_up()
    server.daemon_threads = True
    return server
