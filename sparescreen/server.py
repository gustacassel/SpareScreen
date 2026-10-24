"""HTTP server: serves the page and streams the data over Server-Sent Events."""

import json
import mimetypes
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WEB_DIR = Path(__file__).parent / "web"


class Hub:
    """Holds the latest snapshot and wakes the clients when a new one arrives."""

    def __init__(self):
        self._cond = threading.Condition()
        self._version = 0
        self._payload = None

    def publish(self, snapshot):
        payload = json.dumps(snapshot, separators=(",", ":"))
        with self._cond:
            self._version += 1
            self._payload = payload
            self._cond.notify_all()

    def wait_next(self, last_version, timeout):
        with self._cond:
            self._cond.wait_for(lambda: self._version != last_version, timeout)
            return self._version, self._payload


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


def make_handler(hub, config):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/events":
                self._stream_events()
            else:
                self._serve_static("index.html" if path == "/" else path.lstrip("/"))

        def do_POST(self):
            if self.path.split("?", 1)[0] != "/config" or config is None:
                self.send_error(404)
                return
            try:
                size = min(int(self.headers.get("Content-Length") or 0), 10_000)
                changes = json.loads(self.rfile.read(size) or b"{}")
            except ValueError:
                self.send_error(400)
                return
            body = json.dumps(config.update(changes)).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

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

        def _stream_events(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            version = 0
            try:
                while True:
                    new_version, payload = hub.wait_next(version, timeout=15)
                    if new_version == version or payload is None:
                        self.wfile.write(b": ping\n\n")
                    else:
                        version = new_version
                        self.wfile.write(f"data: {payload}\n\n".encode())
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass  # the phone closed the page or lost the connection

        def log_message(self, fmt, *args):
            if "/events" not in self.path:
                super().log_message(fmt, *args)

    return Handler


def serve(host, port, sources, interval, config=None):
    """`config` (ConfigStore) receives the changes made on the settings screen."""
    hub = Hub()
    start_sampler(hub, sources, interval)
    server = ThreadingHTTPServer((host, port), make_handler(hub, config))
    server.daemon_threads = True
    return server
