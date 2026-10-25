"""What the PC is playing (Spotify, a browser tab, any player), from the OS's own media session.

- Windows: the System Media Transport Controls (the same info as the volume
  flyout), through the pywinrt packages, installed on Windows only.
- Linux: MPRIS over D-Bus, through `playerctl` if installed, else `dbus-send`.
- macOS: best effort. Apple restricted the private MediaRemote framework in
  macOS 15.4, so only the free `media-control` or `nowplaying-cli` tools (from
  Homebrew) work. AppleScript is not used: it asks for permission to control
  each player.
"""

import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import time

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

UNAVAILABLE = {"available": False}
NOTHING = {"available": True, "playing": False}

# Friendly names for the ids each OS reports: Windows AUMIDs ("Spotify.exe",
# "Microsoft.ZuneMusic_8wekyb3d8bbwe!Microsoft.ZuneMusic"), MPRIS names
# ("chromium.instance123") and macOS bundle ids ("com.spotify.client").
# First match wins, so more specific entries come first.
_APPS = (
    ("spotify", "Spotify"),
    ("msedge", "Edge"), ("edgemac", "Edge"), ("microsoftedge", "Edge"),
    ("chromium", "Chromium"), ("chrome", "Chrome"),
    ("308046b0af4a39cb", "Firefox"), ("firefox", "Firefox"),  # Firefox's AUMID on Windows is a hash
    ("brave", "Brave"), ("vivaldi", "Vivaldi"), ("opera", "Opera"), ("safari", "Safari"),
    ("zunemusic", "Media Player"), ("zunevideo", "Movies & TV"), ("com.apple.music", "Music"),
    ("itunes", "iTunes"), ("com.apple.podcasts", "Podcasts"), ("com.apple.tv", "TV"),
    ("vlc", "VLC"), ("foobar2000", "foobar2000"), ("musicbee", "MusicBee"), ("aimp", "AIMP"),
    ("winamp", "Winamp"), ("tidal", "TIDAL"), ("deezer", "Deezer"), ("amazonmusic", "Amazon Music"),
    ("applemusic", "Apple Music"), ("youtube-music", "YouTube Music"), ("rhythmbox", "Rhythmbox"),
    ("elisa", "Elisa"), ("strawberry", "Strawberry"), ("clementine", "Clementine"),
    ("audacious", "Audacious"), ("lollypop", "Lollypop"), ("celluloid", "Celluloid"),
    ("totem", "Videos"), ("kdeconnect", "KDE Connect"), ("mpv", "mpv"),
)
_HEX_ID = re.compile(r"^[0-9a-f]{12,}$")


def friendly_app(raw):
    """Player id as reported by the OS -> a name people recognize ("" if it's just a hash)."""
    raw = str(raw or "").strip()
    low = raw.lower()
    for key, name in _APPS:
        if key in low:
            return name
    name = raw.split("!")[-1]                      # AUMID: Family_hash!App -> App
    name = re.sub(r"(?i)\.exe$", "", name)
    name = re.sub(r"\.instance[_\d]*$", "", name)  # MPRIS: vlc.instance1234
    if name.count(".") >= 2:                       # reverse DNS: org.gnome.Music -> Music
        name = name.split(".")[-1]
    name = name.split("_")[0]
    if not name or _HEX_ID.match(name.lower()):
        return ""
    return name[0].upper() + name[1:] if name.islower() else name


def _seconds(value):
    """Number, or None when missing, invalid or not positive."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if value > 0 and value == value and value != float("inf") else None


def track(title, artist="", album="", app="", status="playing", position=None, duration=None):
    """The "playing" shape every backend returns; None when there is no title."""
    title = str(title or "").strip()
    if not title:
        return None
    duration = _seconds(duration)
    position = (_seconds(position) or 0.0) if duration else None  # a position without a length means nothing
    if position is not None:
        position = round(min(position, duration), 1)
    return {
        "available": True,
        "playing": True,
        "title": title,
        "artist": str(artist or "").strip(),
        "album": str(album or "").strip(),
        "app": app or "",
        "status": "paused" if status == "paused" else "playing",
        "position": position,
        "duration": round(duration, 1) if duration else None,
    }


def _pick(tracks):
    """First playing track, else first paused one (each backend lists the main session first)."""
    tracks = [t for t in tracks if t]
    playing = [t for t in tracks if t["status"] == "playing"]
    return (playing or tracks or [None])[0]


def _run(args, timeout=2.0):
    """stdout of a command, or None if it could not run. Exit codes vary by tool, callers decide."""
    try:
        result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=timeout, creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return result.stdout or ""


def _find(name, extra_dirs=()):
    """A tool on PATH, or in well-known folders (autostart may run with a minimal PATH)."""
    found = shutil.which(name)
    if found:
        return found
    for folder in extra_dirs:
        path = os.path.join(folder, name)
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


# --- Windows -------------------------------------------------------------------------------

# GlobalSystemMediaTransportControlsSessionPlaybackStatus
_WIN_STATUS = {4: "playing", 5: "paused"}


def _timedelta_seconds(value):
    """TimeSpan comes as a timedelta from pywinrt; tolerate raw 100 ns ticks too."""
    if value is None:
        return None
    if hasattr(value, "total_seconds"):
        return value.total_seconds()
    try:
        return float(value) / 1e7
    except (TypeError, ValueError):
        return None


def windows_position(timeline, status, now=None):
    """(position, duration) in seconds from a session's timeline properties.

    Players only update the timeline on events (play, seek...), so while playing
    the position is moved forward by the time since `last_updated_time`.
    """
    start = _timedelta_seconds(getattr(timeline, "start_time", None)) or 0.0
    end = _timedelta_seconds(getattr(timeline, "end_time", None))
    position = _timedelta_seconds(getattr(timeline, "position", None))
    if end is None or position is None or end - start <= 0:
        return None, None  # browsers without position info report all zeros
    position -= start
    updated = getattr(timeline, "last_updated_time", None)
    if status == "playing" and isinstance(updated, datetime.datetime):
        now = now or datetime.datetime.now(datetime.timezone.utc)
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=datetime.timezone.utc)
        elapsed = (now - updated).total_seconds()
        if 0 < elapsed < 24 * 3600:
            position += elapsed
    return position, end - start


class WindowsMedia:
    """System Media Transport Controls, through the pywinrt packages (imported lazily)."""

    WAIT = 1.0  # seconds; these WinRT calls usually answer in a few ms

    def __init__(self):
        self._control = None
        self._manager = None

    def available(self):
        if self._control is None:
            try:
                from winrt.windows.media import control
            except Exception:
                self._control = False
            else:
                self._control = control
                try:  # older pywinrt needs the collections projection to iterate the session list
                    import winrt.windows.foundation.collections  # noqa: F401
                except Exception:
                    pass
        return bool(self._control)

    def _wait(self, operation):
        operation.wait(self.WAIT)
        return operation.get_results()  # raises if it did not complete

    def read(self):
        try:
            if self._manager is None:
                manager_class = self._control.GlobalSystemMediaTransportControlsSessionManager
                self._manager = self._wait(manager_class.request_async())
            return self._read(self._manager)
        except Exception:
            self._manager = None  # start over next time (e.g. the media service restarted)
            raise

    def _read(self, manager):
        current = manager.get_current_session()
        sessions = ([current] if current is not None else []) + list(manager.get_sessions() or [])
        candidates = []
        for session in sessions:
            status = _WIN_STATUS.get(int(session.get_playback_info().playback_status))
            if status:
                candidates.append((status != "playing", len(candidates), status, session))
        for _, _, status, session in sorted(candidates, key=lambda c: c[:2]):
            props = self._wait(session.try_get_media_properties_async())
            if props is None:
                continue
            position, duration = windows_position(session.get_timeline_properties(), status)
            found = track(props.title, props.artist, props.album_title,
                          friendly_app(session.source_app_user_model_id), status, position, duration)
            if found:
                return found
        return None


# --- Linux ---------------------------------------------------------------------------------

_SEP = "\x1f"  # unit separator: never part of a song title
_PLAYERCTL_FORMAT = _SEP.join(("{{status}}", "{{playerName}}", "{{title}}", "{{artist}}", "{{album}}",
                               "{{position}}", "{{mpris:length}}"))
_MPRIS_STATUS = {"Playing": "playing", "Paused": "paused"}


def parse_playerctl(text):
    """`playerctl --all-players metadata --format ...` -> track. Times are in microseconds."""
    tracks = []
    for line in (text or "").splitlines():
        fields = line.split(_SEP)
        if len(fields) != 7:
            continue
        status, player, title, artist, album, position, length = fields
        status = _MPRIS_STATUS.get(status.strip())
        if status:
            tracks.append(track(title, artist, album, friendly_app(player), status,
                                (_seconds(position) or 0) / 1e6, (_seconds(length) or 0) / 1e6))
    return _pick(tracks)


def _dbus_value(body):
    """'string "Playing"' -> 'Playing'; 'int64 1234' -> 1234.0."""
    kind, _, value = body.partition(" ")
    value = value.strip()
    if kind == "string":
        return value[1:-1] if len(value) >= 2 and value[0] == '"' and value[-1] == '"' else value
    try:
        return float(value)
    except ValueError:
        return value


def parse_dbus_names(text):
    """`dbus-send ... ListNames` -> the MPRIS player bus names."""
    names = re.findall(r'string "(org\.mpris\.MediaPlayer2\.[^"]+)"', text or "")
    return [n for n in names if not n.startswith("org.mpris.MediaPlayer2.playerctld")]  # a proxy, not a player


def parse_dbus_properties(text):
    """`dbus-send --print-reply ... Properties.GetAll` -> flat {key: value}, Metadata included.

    The output lists each dict entry as a `string "key"` line followed by a
    `variant ...` line; string arrays (artists) span lines until `]`.
    """
    values, key, collecting = {}, None, None
    for line in (text or "").splitlines():
        line = line.strip()
        if collecting is not None:
            if line == "]":
                values[key] = ", ".join(collecting)
                key, collecting = None, None
            elif line.startswith("string "):
                collecting.append(_dbus_value(line))
            continue
        if line.startswith("variant"):
            body = line[len("variant"):].strip()
            if key is not None and body.startswith("array ["):
                if key in ("xesam:artist", "xesam:albumArtist"):
                    collecting = []
                    continue
                key = None  # e.g. Metadata: its own entries follow
            elif key is not None:
                values[key] = _dbus_value(body)
                key = None
        elif line.startswith("string "):
            key = _dbus_value(line)
    return values


def dbus_track(name, values):
    status = _MPRIS_STATUS.get(values.get("PlaybackStatus"))
    if not status:
        return None
    length = _seconds(values.get("mpris:length"))
    position = _seconds(values.get("Position"))
    return track(values.get("xesam:title"), values.get("xesam:artist") or values.get("xesam:albumArtist"),
                 values.get("xesam:album"), friendly_app(name.replace("org.mpris.MediaPlayer2.", "")), status,
                 position / 1e6 if position else None, length / 1e6 if length else None)


class LinuxMedia:
    """MPRIS players over D-Bus: `playerctl` if installed, else plain `dbus-send`."""

    def __init__(self):
        self.playerctl = _find("playerctl")
        self.dbus_send = None if self.playerctl else _find("dbus-send")

    def available(self):
        return bool(self.playerctl or self.dbus_send)

    def read(self):
        if self.playerctl:
            return parse_playerctl(_run([self.playerctl, "--all-players", "metadata", "--format",
                                         _PLAYERCTL_FORMAT]))
        names = parse_dbus_names(_run([self.dbus_send, "--session", "--print-reply", "--reply-timeout=1000",
                                       "--dest=org.freedesktop.DBus", "/org/freedesktop/DBus",
                                       "org.freedesktop.DBus.ListNames"]))
        tracks = []
        for name in names[:8]:  # a hung player costs at most its timeout
            reply = _run([self.dbus_send, "--session", "--print-reply", "--reply-timeout=1000", "--dest=" + name,
                          "/org/mpris/MediaPlayer2", "org.freedesktop.DBus.Properties.GetAll",
                          "string:org.mpris.MediaPlayer2.Player"], timeout=1.5)
            tracks.append(dbus_track(name, parse_dbus_properties(reply)))
        return _pick(tracks)


# --- macOS ---------------------------------------------------------------------------------

_BREW_DIRS = ("/opt/homebrew/bin", "/usr/local/bin")
_NOWPLAYING_FIELDS = ("title", "artist", "album", "duration", "elapsedTime", "playbackRate")


def parse_media_control(text):
    """`media-control get --now --no-artwork` -> track. It prints `null` when nothing is playing."""
    try:
        data = json.loads(text or "null")
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    app = data.get("parentApplicationBundleIdentifier") or data.get("bundleIdentifier")
    position = data.get("elapsedTimeNow")
    if position is None:
        position = data.get("elapsedTime")
    return track(data.get("title"), data.get("artist"), data.get("album"), friendly_app(app),
                 "playing" if data.get("playing") else "paused", position, data.get("duration"))


def parse_nowplaying(text):
    """`nowplaying-cli get title artist ...` -> track. One value per line, `null` when missing."""
    lines = (text or "").splitlines()
    if len(lines) < len(_NOWPLAYING_FIELDS):
        return None
    values = dict(zip(_NOWPLAYING_FIELDS, (None if v.strip() == "null" else v.strip() for v in lines)))
    status = "playing" if (_seconds(values["playbackRate"]) or 0) > 0 else "paused"
    return track(values["title"], values["artist"], values["album"], "", status,
                 values["elapsedTime"], values["duration"])


class MacMedia:
    """Best effort: `media-control` (works on macOS 15.4+) or `nowplaying-cli`, if installed."""

    def __init__(self):
        self.media_control = _find("media-control", _BREW_DIRS)
        self.nowplaying = None if self.media_control else _find("nowplaying-cli", _BREW_DIRS)

    def available(self):
        return bool(self.media_control or self.nowplaying)

    def read(self):
        if self.media_control:
            return parse_media_control(_run([self.media_control, "get", "--now", "--no-artwork"], timeout=3))
        return parse_nowplaying(_run([self.nowplaying, "get"] + list(_NOWPLAYING_FIELDS)))


# --- Source --------------------------------------------------------------------------------

def default_backend(platform=None):
    platform = platform or sys.platform
    if platform == "win32":
        return WindowsMedia()
    if platform == "darwin":
        return MacMedia()
    if platform.startswith("linux") or "bsd" in platform:
        return LinuxMedia()
    return None


class MediaSource:
    """Now playing. Asks the OS every INTERVAL seconds; in between, moves the position forward."""

    name = "media"
    INTERVAL = 2

    def __init__(self, backend=None):
        self.backend = backend if backend is not None else default_backend()
        self._at = None
        self._last = UNAVAILABLE

    def read(self):
        try:
            return self._read()
        except Exception:
            return dict(NOTHING)

    def _read(self):
        now = time.time()
        if self._at is None or now - self._at >= self.INTERVAL:
            self._at = now
            self._last = self._fetch()
        data = dict(self._last)
        if data.get("status") == "playing" and data.get("position") is not None:
            data["position"] = round(min(data["position"] + now - self._at, data["duration"]), 1)
        return data

    def _fetch(self):
        if self.backend is None or not self.backend.available():
            return UNAVAILABLE
        try:
            found = self.backend.read()
        except Exception:
            found = None
        return found or NOTHING
