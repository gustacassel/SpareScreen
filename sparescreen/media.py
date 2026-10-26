"""What the PC is playing (Spotify, a browser tab, any player), from the OS's own media session.

- Windows: the System Media Transport Controls (the same info as the volume
  flyout), through the pywinrt packages, installed on Windows only.
- Linux: MPRIS over D-Bus, through `playerctl` if installed, else `dbus-send`.
- macOS: best effort. Apple restricted the private MediaRemote framework in
  macOS 15.4, so only the free `media-control` or `nowplaying-cli` tools (from
  Homebrew) work. AppleScript is not used: it asks for permission to control
  each player.

Album covers come from the session itself (Windows thumbnail, a local MPRIS
artUrl, media-control's artwork) and are never downloaded from the internet.
The player's icon is only found on Windows, from the running program.

The Music screen's buttons (previous, play/pause, next) go back the same way, to the
player being shown: the session's own commands on Windows, `playerctl` or an MPRIS
method call on Linux, `media-control` or `nowplaying-cli` on macOS. "controls" says
which ones the player accepts (Windows and MPRIS tell; elsewhere all three are offered).
"""

from __future__ import annotations

import base64
import binascii
import datetime
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
from typing import Any, Callable, Iterable, Iterator, Optional, Sequence, Union
from urllib.parse import unquote, urlparse

import psutil

from . import icons, images
from .shapes import Json

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

UNAVAILABLE: Json = {"available": False}
NOTHING: Json = {"available": True, "playing": False}
ACTIONS = ("previous", "play_pause", "next")
ALL_CONTROLS: Json = {"previous": True, "play_pause": True, "next": True}

Loader = Callable[[str], Optional[str]]  # image key -> its URL (images.put), loaded only when needed

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


def friendly_app(raw: object) -> str:
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


def _seconds(value: Any) -> float | None:
    """Number, or None when missing, invalid or not positive."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 and number == number and number != float("inf") else None


def track(title: object, artist: object = "", album: object = "", app: str = "", status: str = "playing",
          position: object = None, duration: object = None) -> Json | None:
    """The "playing" shape every backend returns; None when there is no title."""
    title = str(title or "").strip()
    if not title:
        return None
    duration = _seconds(duration)
    position = (_seconds(position) or 0.0) if duration else None  # a position without a length means nothing
    if position is not None and duration:
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
        "art": None,       # filled by MediaSource from the backend's "_art" loader
        "app_icon": None,  # same, from "_icon"
        "controls": dict(ALL_CONTROLS),  # the buttons this player accepts
    }


def image_type(data: bytes) -> str:
    """Content type from the first bytes; covers are almost always JPEG or PNG."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"GIF":
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def _pick(tracks: Iterable[Json | None]) -> Json | None:
    """First playing track, else first paused one (each backend lists the main session first)."""
    found = [t for t in tracks if t]
    playing = [t for t in found if t["status"] == "playing"]
    return next(iter(playing or found), None)


def _run(args: Sequence[str], timeout: float = 2.0) -> str | None:
    """stdout of a command, or None if it could not run. Exit codes vary by tool, callers decide."""
    try:
        result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=timeout, creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return result.stdout or ""


def _find(name: str, extra_dirs: Iterable[str] = ()) -> str | None:
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


def _timedelta_seconds(value: Any) -> float | None:
    """TimeSpan comes as a timedelta from pywinrt; tolerate raw 100 ns ticks too."""
    if value is None:
        return None
    if hasattr(value, "total_seconds"):
        return float(value.total_seconds())
    try:
        return float(value) / 1e7
    except (TypeError, ValueError):
        return None


def windows_controls(controls: Any) -> Json:
    """Which buttons a session accepts (its PlaybackControls); all of them when it doesn't say."""
    if controls is None:
        return dict(ALL_CONTROLS)
    play_pause = any(getattr(controls, name, False) for name in
                     ("is_play_pause_toggle_enabled", "is_play_enabled", "is_pause_enabled"))
    return {"previous": bool(getattr(controls, "is_previous_enabled", False)), "play_pause": play_pause,
            "next": bool(getattr(controls, "is_next_enabled", False))}


def windows_position(timeline: Any, status: str,
                     now: datetime.datetime | None = None) -> tuple[float | None, float | None]:
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

    def __init__(self) -> None:
        self._control: Any = None  # the winrt module once imported, False if it can't be
        self._manager: Any = None

    def available(self) -> bool:
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

    def _wait(self, operation: Any) -> Any:
        operation.wait(self.WAIT)
        return operation.get_results()  # raises if it did not complete

    def read(self) -> Json | None:
        try:
            if self._manager is None:
                manager_class = self._control.GlobalSystemMediaTransportControlsSessionManager
                self._manager = self._wait(manager_class.request_async())
            return self._read(self._manager)
        except Exception:
            self._manager = None  # start over next time (e.g. the media service restarted)
            raise

    def _read(self, manager: Any) -> Json | None:
        current = manager.get_current_session()
        sessions = ([current] if current is not None else []) + list(manager.get_sessions() or [])
        candidates: list[tuple[bool, int, str, Any]] = []
        for session in sessions:
            status = _WIN_STATUS.get(int(session.get_playback_info().playback_status))
            if status:
                candidates.append((status != "playing", len(candidates), status, session))
        for _, _, status, session in sorted(candidates, key=lambda c: c[:2]):
            props = self._wait(session.try_get_media_properties_async())
            if props is None:
                continue
            position, duration = windows_position(session.get_timeline_properties(), status)
            aumid = session.source_app_user_model_id
            found = track(props.title, props.artist, props.album_title, friendly_app(aumid), status,
                          position, duration)
            if found:
                found["controls"] = windows_controls(getattr(session.get_playback_info(), "controls", None))
                found["_target"] = session  # where the buttons go
                thumbnail = getattr(props, "thumbnail", None)
                if thumbnail is not None:
                    found["_art"] = lambda key, ref=thumbnail: self._thumbnail(ref, key)
                found["_icon"] = (aumid, lambda key: windows_app_icon(aumid, key))
                return found
        return None

    def control(self, session: Any, action: str, status: str | None) -> bool:
        if action == "next":
            operation = session.try_skip_next_async()
        elif action == "previous":
            operation = session.try_skip_previous_async()
        else:
            # Some players (browsers) offer play and pause but not the toggle.
            controls = getattr(session.get_playback_info(), "controls", None)
            if status == "playing" and getattr(controls, "is_pause_enabled", False):
                operation = session.try_pause_async()
            elif status == "paused" and getattr(controls, "is_play_enabled", False):
                operation = session.try_play_async()
            else:
                operation = session.try_toggle_play_pause_async()
        return bool(self._wait(operation))

    def _thumbnail(self, reference: Any, key: str) -> str | None:
        """The cover the player gave Windows (an IRandomAccessStreamReference) -> image URL."""
        from winrt.windows.storage.streams import Buffer, InputStreamOptions

        stream = self._wait(reference.open_read_async())
        try:
            size = int(stream.size)
            if not 0 < size <= images.MAX_BYTES:
                return None
            data = bytes(self._wait(stream.read_async(Buffer(size), size, InputStreamOptions.READ_AHEAD)))
            content_type = str(getattr(stream, "content_type", "") or "")
        finally:
            try:
                stream.close()
            except Exception:
                pass
        if not content_type.startswith("image/"):
            content_type = image_type(data)
        return images.put(key, data, content_type)


def _processes() -> Iterator[tuple[str, str | None]]:
    """(name, exe path) of running programs; exe is None for those we can't inspect."""
    for proc in psutil.process_iter(["name", "exe"]):
        yield proc.info.get("name") or "", proc.info.get("exe")


def windows_app_icon(aumid: object, key: str,
                     processes: Iterable[tuple[str, str | None]] | None = None) -> str | None:
    """Icon of the player behind a Windows media session -> image URL, or None.

    Desktop players report their exe name ("Spotify.exe") or a short name
    ("Chrome", "MSEdge"); Store apps report "Package.Name_publisherid!App" and
    run from a folder named "Package.Name_<version>_<arch>__publisherid".
    """
    aumid = str(aumid or "")
    family, bang, _ = aumid.partition("!")
    procs = list(_processes() if processes is None else processes)
    if bang and "_" in family:
        name, _, publisher = family.rpartition("_")
        folder = re.compile(r"[\\/]" + re.escape(name) + r"_[^\\/]*_" + re.escape(publisher) + r"[\\/]", re.I)
        for _, exe in procs:
            if exe and folder.search(exe):
                return package_logo(exe, key) or images.put(key, icons.exe_icon_png(exe), "image/png")
        return None
    wanted = {aumid.lower(), aumid.lower() + ".exe"}
    friendly = friendly_app(aumid)
    if friendly:
        wanted.add(friendly.lower() + ".exe")  # e.g. Firefox, whose id is a hash
    for name, exe in procs:
        if exe and name.lower() in wanted:
            return images.put(key, icons.exe_icon_png(exe), "image/png")
    return None


_MANIFEST_LOGOS = ("Square150x150Logo", "Square44x44Logo")


def package_logo(exe: str, key: str) -> str | None:
    """A Store app's logo, from the AppxManifest.xml next to its exe (or a few folders up)."""
    folder = os.path.dirname(exe)
    for _ in range(4):
        manifest = os.path.join(folder, "AppxManifest.xml")
        if os.path.isfile(manifest):
            break
        folder = os.path.dirname(folder)
    else:
        return None
    try:
        with open(manifest, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return None
    paths = [m.group(1) for attr in _MANIFEST_LOGOS for m in [re.search(attr + r'="([^"]+)"', text)] if m]
    paths += re.findall(r"<Logo>([^<]+)</Logo>", text)
    for relative in paths:
        path = os.path.join(folder, *re.split(r"[\\/]", relative.strip()))
        stem, ext = os.path.splitext(path)
        # The file named in the manifest often only exists with a qualifier:
        # Square44x44Logo.targetsize-256.png, Logo.scale-200.png... Take the biggest.
        variants = [path] + [p for p in glob.glob(glob.escape(stem) + ".*" + ext) if "contrast" not in p.lower()]
        variants = [p for p in variants if os.path.isfile(p)]
        if variants:
            return images.put_file(key, max(variants, key=os.path.getsize))
    return None


# --- Linux ---------------------------------------------------------------------------------

_SEP = "\x1f"  # unit separator: never part of a song title
_PLAYERCTL_FORMAT = _SEP.join(("{{status}}", "{{playerName}}", "{{title}}", "{{artist}}", "{{album}}",
                               "{{position}}", "{{mpris:length}}", "{{mpris:artUrl}}"))
_MPRIS_STATUS = {"Playing": "playing", "Paused": "paused"}


def file_art(url: object) -> Loader | None:
    """Loader for an MPRIS artUrl, only when it's a local file: covers are never downloaded."""
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme != "file" or parsed.netloc not in ("", "localhost") or not parsed.path:
        return None
    path = unquote(parsed.path)
    return lambda key: images.put_file(key, path)


def _with_art(found: Json | None, loader: Loader | None) -> Json | None:
    if found and loader:
        found["_art"] = loader
    return found


def parse_playerctl(text: str | None) -> Json | None:
    """`playerctl --all-players metadata --format ...` -> track. Times are in microseconds."""
    tracks = []
    for line in (text or "").splitlines():
        fields = line.split(_SEP)
        if len(fields) != 8:
            continue
        state, player, title, artist, album, position, length, art = fields
        status = _MPRIS_STATUS.get(state.strip())
        if status:
            found = track(title, artist, album, friendly_app(player), status,
                          (_seconds(position) or 0) / 1e6, (_seconds(length) or 0) / 1e6)
            if found:
                found["_target"] = player
            tracks.append(_with_art(found, file_art(art)))
    return _pick(tracks)


def _dbus_value(body: str) -> str | float:
    """'string "Playing"' -> 'Playing'; 'int64 1234' -> 1234.0."""
    kind, _, value = body.partition(" ")
    value = value.strip()
    if kind == "string":
        return value[1:-1] if len(value) >= 2 and value[0] == '"' and value[-1] == '"' else value
    try:
        return float(value)
    except ValueError:
        return value


def parse_dbus_names(text: str | None) -> list[str]:
    """`dbus-send ... ListNames` -> the MPRIS player bus names."""
    names = re.findall(r'string "(org\.mpris\.MediaPlayer2\.[^"]+)"', text or "")
    return [n for n in names if not n.startswith("org.mpris.MediaPlayer2.playerctld")]  # a proxy, not a player


def parse_dbus_properties(text: str | None) -> Json:
    """`dbus-send --print-reply ... Properties.GetAll` -> flat {key: value}, Metadata included.

    The output lists each dict entry as a `string "key"` line followed by a
    `variant ...` line; string arrays (artists) span lines until `]`.
    """
    values: Json = {}
    key: Any = None
    collecting: list[Any] | None = None
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


def dbus_track(name: str, values: Json) -> Json | None:
    status = _MPRIS_STATUS.get(values.get("PlaybackStatus", ""))
    if not status:
        return None
    length = _seconds(values.get("mpris:length"))
    position = _seconds(values.get("Position"))
    found = track(values.get("xesam:title"), values.get("xesam:artist") or values.get("xesam:albumArtist"),
                  values.get("xesam:album"), friendly_app(name.replace("org.mpris.MediaPlayer2.", "")), status,
                  position / 1e6 if position else None, length / 1e6 if length else None)
    if found:
        # MPRIS says what the player allows; a property it doesn't send counts as allowed.
        found["controls"] = {"previous": values.get("CanGoPrevious") != "false",
                             "play_pause": values.get("CanPause") != "false" or values.get("CanPlay") != "false",
                             "next": values.get("CanGoNext") != "false"}
        found["_target"] = name
    return _with_art(found, file_art(values.get("mpris:artUrl")))


class LinuxMedia:
    """MPRIS players over D-Bus: `playerctl` if installed, else plain `dbus-send`."""

    def __init__(self) -> None:
        self.playerctl = _find("playerctl")
        self.dbus_send = None if self.playerctl else _find("dbus-send")

    def available(self) -> bool:
        return bool(self.playerctl or self.dbus_send)

    def read(self) -> Json | None:
        if self.playerctl:
            return parse_playerctl(_run([self.playerctl, "--all-players", "metadata", "--format",
                                         _PLAYERCTL_FORMAT]))
        assert self.dbus_send is not None  # only read when available()
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

    def control(self, player: str, action: str, status: str | None) -> bool:
        if self.playerctl:
            command = {"previous": "previous", "play_pause": "play-pause", "next": "next"}[action]
            return _run([self.playerctl, "--player=" + player, command]) is not None
        assert self.dbus_send is not None  # only shown a player when available()
        method = {"previous": "Previous", "play_pause": "PlayPause", "next": "Next"}[action]
        return _run([self.dbus_send, "--session", "--type=method_call", "--dest=" + player,
                     "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player." + method]) is not None


# --- macOS ---------------------------------------------------------------------------------

_BREW_DIRS = ("/opt/homebrew/bin", "/usr/local/bin")
_NOWPLAYING_FIELDS = ("title", "artist", "album", "duration", "elapsedTime", "playbackRate")


def base64_art(encoded: object, content_type: object = None) -> Loader | None:
    """Loader for artwork sent as base64 (media-control's artworkData)."""
    if not encoded or not isinstance(encoded, str):
        return None

    def load(key: str) -> str | None:
        try:
            data = base64.b64decode(encoded)
        except (binascii.Error, ValueError):
            return None
        kind = content_type if isinstance(content_type, str) and content_type.startswith("image/") else None
        return images.put(key, data, kind or image_type(data))
    return load


def parse_media_control(text: str | None) -> Json | None:
    """`media-control get --now` -> track. It prints `null` when nothing is playing."""
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
    found = track(data.get("title"), data.get("artist"), data.get("album"), friendly_app(app),
                  "playing" if data.get("playing") else "paused", position, data.get("duration"))
    if found:
        found["_target"] = True  # media-control acts on whatever macOS is playing
    return _with_art(found, base64_art(data.get("artworkData"), data.get("artworkMimeType")))


def parse_nowplaying(text: str | None) -> Json | None:
    """`nowplaying-cli get title artist ...` -> track. One value per line, `null` when missing."""
    lines = (text or "").splitlines()
    if len(lines) < len(_NOWPLAYING_FIELDS):
        return None
    values = dict(zip(_NOWPLAYING_FIELDS, (None if v.strip() == "null" else v.strip() for v in lines)))
    status = "playing" if (_seconds(values["playbackRate"]) or 0) > 0 else "paused"
    found = track(values["title"], values["artist"], values["album"], "", status,
                  values["elapsedTime"], values["duration"])
    if found:
        found["_target"] = True  # nowplaying-cli acts on whatever macOS is playing
    return found


class MacMedia:
    """Best effort: `media-control` (works on macOS 15.4+) or `nowplaying-cli`, if installed."""

    def __init__(self) -> None:
        self.media_control = _find("media-control", _BREW_DIRS)
        self.nowplaying = None if self.media_control else _find("nowplaying-cli", _BREW_DIRS)

    def available(self) -> bool:
        return bool(self.media_control or self.nowplaying)

    def read(self) -> Json | None:
        if self.media_control:
            # With the artwork (base64, decoded only when the track changes).
            return parse_media_control(_run([self.media_control, "get", "--now"], timeout=3))
        assert self.nowplaying is not None  # only read when available()
        return parse_nowplaying(_run([self.nowplaying, "get"] + list(_NOWPLAYING_FIELDS)))

    def control(self, target: object, action: str, status: str | None) -> bool:
        if self.media_control:
            command = {"previous": "previous-track", "play_pause": "toggle-play-pause", "next": "next-track"}[action]
            return _run([self.media_control, command]) is not None
        assert self.nowplaying is not None  # only shown a track when available()
        command = {"previous": "previous", "play_pause": "togglePlayPause", "next": "next"}[action]
        return _run([self.nowplaying, command]) is not None


# --- Source --------------------------------------------------------------------------------

Backend = Union[WindowsMedia, MacMedia, LinuxMedia]


def default_backend(platform: str | None = None) -> Backend | None:
    platform = platform or sys.platform
    if platform == "win32":
        return WindowsMedia()
    if platform == "darwin":
        return MacMedia()
    if platform.startswith("linux") or "bsd" in platform:
        return LinuxMedia()
    return None


class _Image:
    """One image slot (cover or player icon), loaded only when what it shows changes.

    `always` loads per change: covers get 2, because Windows players sometimes
    still hand out the previous cover right after skipping. While nothing was
    found, it keeps trying up to `tries` times (some players send it late).
    """

    _url: str | None

    def __init__(self, key: str, always: int, tries: int) -> None:
        self.key, self.always, self.tries = key, always, tries
        self._id, self._url, self._loads = object(), None, 0

    def get(self, ident: object, loader: Loader | None) -> str | None:
        if ident != self._id:
            self._id, self._url, self._loads = ident, None, 0
        if loader and (self._loads < self.always or (self._url is None and self._loads < self.tries)):
            self._loads += 1
            try:
                self._url = loader(self.key) or self._url
            except Exception:
                pass
        return self._url


class MediaSource:
    """Now playing. Asks the OS every INTERVAL seconds; in between, moves the position forward."""

    name = "media"
    INTERVAL = 2

    def __init__(self, backend: Backend | None = None) -> None:
        self.backend = backend if backend is not None else default_backend()
        self._at: float | None = None
        self._last = UNAVAILABLE
        self._art = _Image("media-art", always=2, tries=4)
        self._icon = _Image("media-app-icon", always=1, tries=3)
        self._target: Any = None  # the player shown now, for control()

    def read(self) -> Json:
        try:
            return self._read()
        except Exception:
            return dict(NOTHING)

    def _read(self) -> Json:
        now = time.time()
        if self._at is None or now - self._at >= self.INTERVAL:
            self._at = now
            self._last = self._fetch()
        data = dict(self._last)
        if data.get("status") == "playing" and data.get("position") is not None:
            data["position"] = round(min(data["position"] + now - self._at, data["duration"]), 1)
        return data

    def _fetch(self) -> Json:
        self._target = None
        if self.backend is None or not self.backend.available():
            return UNAVAILABLE
        try:
            found = self.backend.read()
        except Exception:
            found = None
        if not found:
            return NOTHING
        self._target = found.pop("_target", None)
        if self._target is None:
            found["controls"] = {action: False for action in ACTIONS}  # nowhere to send them
        art = found.pop("_art", None)
        icon_id, icon = found.pop("_icon", None) or (None, None)
        found["art"] = self._art.get((found["app"], found["title"], found["artist"], found["album"]), art)
        found["app_icon"] = self._icon.get(icon_id, icon)
        return found

    def control(self, action: str) -> bool:
        """Previous, play/pause or next on the player shown now (the Music screen's buttons)."""
        target, status = self._target, self._last.get("status")
        if action not in ACTIONS or target is None or self.backend is None:
            return False
        try:
            done = self.backend.control(target, action, status)
        except Exception:
            return False
        self._at = None  # ask the player again right away, so the page sees the change
        return done
