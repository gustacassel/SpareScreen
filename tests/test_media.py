"""Now playing: each OS's output is parsed from samples, no real player needed."""

import datetime
import unittest
from types import SimpleNamespace
from unittest import mock

from sparescreen import media
from sparescreen.demo import DemoMedia
from sparescreen.media import MediaSource

PLAYING_KEYS = {"available", "playing", "title", "artist", "album", "app", "status", "position", "duration"}
S = media._SEP


class FakeBackend:
    def __init__(self, result=None, available=True, error=None):
        self.result, self._available, self.error, self.calls = result, available, error, 0

    def available(self):
        return self._available

    def read(self):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


class SourceTest(unittest.TestCase):
    def test_shapes(self):
        self.assertEqual(MediaSource(FakeBackend(available=False)).read(), {"available": False})
        self.assertEqual(MediaSource(FakeBackend(None)).read(), {"available": True, "playing": False})
        with mock.patch.object(media, "default_backend", return_value=None):
            self.assertEqual(MediaSource().read(), {"available": False})

    def test_errors_never_escape(self):
        source = MediaSource(FakeBackend(error=RuntimeError("boom")))
        self.assertEqual(source.read(), {"available": True, "playing": False})

    def test_throttled_and_position_moves(self):
        backend = FakeBackend(media.track("Song", "Band", "", "Spotify", "playing", 10, 200))
        source = MediaSource(backend)
        with mock.patch("sparescreen.media.time.time", return_value=1000.0):
            first = source.read()
        with mock.patch("sparescreen.media.time.time", return_value=1001.5):
            second = source.read()
        self.assertEqual(backend.calls, 1)
        self.assertEqual(set(first), PLAYING_KEYS)
        self.assertEqual(first["position"], 10)
        self.assertEqual(second["position"], 11.5)
        with mock.patch("sparescreen.media.time.time", return_value=1002.5):
            source.read()
        self.assertEqual(backend.calls, 2)

    def test_paused_position_stays(self):
        source = MediaSource(FakeBackend(media.track("Song", status="paused", position=10, duration=200)))
        with mock.patch("sparescreen.media.time.time", return_value=1000.0):
            source.read()
        with mock.patch("sparescreen.media.time.time", return_value=1001.5):
            self.assertEqual(source.read()["position"], 10)

    def test_track_cleanup(self):
        self.assertIsNone(media.track("  "))
        data = media.track(" Song ", None, None, None, "weird", 500, 200)
        self.assertEqual((data["title"], data["artist"], data["status"], data["position"]), ("Song", "", "playing", 200))
        no_length = media.track("Live stream", position=30, duration=0)
        self.assertEqual((no_length["position"], no_length["duration"]), (None, None))

    def test_demo_matches(self):
        demo = DemoMedia().read()
        self.assertEqual(set(demo), PLAYING_KEYS)
        self.assertEqual(set(demo), set(media.track("x", position=1, duration=2)))


class FriendlyAppTest(unittest.TestCase):
    def test_names(self):
        cases = {
            "Spotify.exe": "Spotify",
            "SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify": "Spotify",
            "Chrome": "Chrome",
            "MSEdge": "Edge",
            "308046B0AF4A39CB": "Firefox",
            "Microsoft.ZuneMusic_8wekyb3d8bbwe!Microsoft.ZuneMusic": "Media Player",
            "chromium.instance12345": "Chromium",
            "com.spotify.client": "Spotify",
            "org.gnome.Lollypop": "Lollypop",
            "someplayer.exe": "Someplayer",
            "org.example.CoolTunes": "CoolTunes",
            "ABCDEF0123456789": "",
            "": "",
            None: "",
        }
        for raw, expected in cases.items():
            self.assertEqual(media.friendly_app(raw), expected, raw)


def _session(aumid, status, title, artist="", album="", position=0, end=0, updated=None):
    props = SimpleNamespace(title=title, artist=artist, album_title=album)
    timeline = SimpleNamespace(start_time=datetime.timedelta(0), end_time=datetime.timedelta(seconds=end),
                               position=datetime.timedelta(seconds=position), last_updated_time=updated)
    return SimpleNamespace(
        source_app_user_model_id=aumid,
        get_playback_info=lambda: SimpleNamespace(playback_status=status),
        try_get_media_properties_async=lambda: _Done(props),
        get_timeline_properties=lambda: timeline,
    )


class _Done:
    """A finished WinRT async operation."""

    def __init__(self, value):
        self.value = value

    def wait(self, timeout):
        return 1

    def get_results(self):
        return self.value


class WindowsTest(unittest.TestCase):
    def _backend(self, current, sessions):
        manager = SimpleNamespace(get_current_session=lambda: current, get_sessions=lambda: sessions)
        control = SimpleNamespace(GlobalSystemMediaTransportControlsSessionManager=SimpleNamespace(
            request_async=lambda: _Done(manager)))
        backend = media.WindowsMedia()
        backend._control = control
        return backend

    def test_prefers_playing_and_skips_untitled(self):
        paused = _session("Chrome", 5, "A video", end=600, position=20)
        untitled = _session("python.exe", 4, "")
        spotify = _session("Spotify.exe", 4, "Song", "Band", "Album", position=30, end=200)
        backend = self._backend(paused, [paused, untitled, spotify])
        data = backend.read()
        self.assertEqual((data["title"], data["artist"], data["album"], data["app"], data["status"]),
                         ("Song", "Band", "Album", "Spotify", "playing"))
        self.assertEqual(data["duration"], 200)

    def test_paused_and_nothing(self):
        paused = _session("Chrome", 5, "A video", end=600, position=20)
        self.assertEqual(self._backend(paused, [paused]).read()["status"], "paused")
        self.assertIsNone(self._backend(None, []).read())
        stopped = _session("Spotify.exe", 3, "Song")
        self.assertIsNone(self._backend(None, [stopped]).read())

    def test_position_moves_forward_while_playing(self):
        now = datetime.datetime(2026, 1, 1, 12, 0, 10, tzinfo=datetime.timezone.utc)
        timeline = SimpleNamespace(start_time=datetime.timedelta(0), end_time=datetime.timedelta(seconds=200),
                                   position=datetime.timedelta(seconds=30),
                                   last_updated_time=now - datetime.timedelta(seconds=10))
        self.assertEqual(media.windows_position(timeline, "playing", now), (40, 200))
        self.assertEqual(media.windows_position(timeline, "paused", now), (30, 200))
        zeros = SimpleNamespace(start_time=datetime.timedelta(0), end_time=datetime.timedelta(0),
                                position=datetime.timedelta(0), last_updated_time=now)
        self.assertEqual(media.windows_position(zeros, "playing", now), (None, None))

    def test_ticks_tolerated(self):
        self.assertEqual(media._timedelta_seconds(25 * 10 ** 7), 25)

    def test_failure_resets_manager(self):
        backend = self._backend(None, [])
        backend._control.GlobalSystemMediaTransportControlsSessionManager.request_async = mock.Mock(
            side_effect=OSError("no service"))
        with self.assertRaises(OSError):
            backend.read()
        self.assertIsNone(backend._manager)
        self.assertEqual(MediaSource(backend).read(), {"available": True, "playing": False})

    def test_missing_package_is_unavailable(self):
        backend = media.WindowsMedia()
        with mock.patch.dict("sys.modules", {"winrt": None, "winrt.windows.media": None}):
            self.assertFalse(backend.available())
        self.assertEqual(MediaSource(backend).read(), {"available": False})


DBUS_NAMES = """method return time=1.2 sender=org.freedesktop.DBus -> destination=:1.5 serial=3 reply_serial=2
   array [
      string "org.freedesktop.DBus"
      string ":1.7"
      string "org.mpris.MediaPlayer2.playerctld"
      string "org.mpris.MediaPlayer2.firefox.instance_1_84"
      string "org.mpris.MediaPlayer2.spotify"
   ]
"""

DBUS_PROPS = """method return time=1.3 sender=:1.42 -> destination=:1.99 serial=8 reply_serial=2
   array [
      dict entry(
         string "PlaybackStatus"
         variant             string "Playing"
      )
      dict entry(
         string "Metadata"
         variant             array [
               dict entry(
                  string "mpris:trackid"
                  variant                      object path "/com/spotify/track/abc"
               )
               dict entry(
                  string "xesam:genre"
                  variant                      array [
                        string "Synthwave"
                     ]
               )
               dict entry(
                  string "xesam:title"
                  variant                      string "Song "Quoted" Title"
               )
               dict entry(
                  string "xesam:artist"
                  variant                      array [
                        string "Band"
                        string "Guest"
                     ]
               )
               dict entry(
                  string "xesam:album"
                  variant                      string "Album"
               )
               dict entry(
                  string "mpris:length"
                  variant                      uint64 215000000
               )
            ]
      )
      dict entry(
         string "Volume"
         variant             double 1
      )
      dict entry(
         string "Position"
         variant             int64 61500000
      )
   ]
"""


class LinuxTest(unittest.TestCase):
    def test_playerctl(self):
        text = (S.join(["Paused", "firefox", "A video", "Channel", "", "1000000", "600000000"]) + "\n"
                + S.join(["Playing", "spotify", "Song", "Band", "Album", "61500000", "215000000"]) + "\n"
                + "No player could handle this command\n")
        data = media.parse_playerctl(text)
        self.assertEqual(set(data), PLAYING_KEYS)
        self.assertEqual((data["title"], data["app"], data["status"], data["position"], data["duration"]),
                         ("Song", "Spotify", "playing", 61.5, 215))

    def test_playerctl_paused_or_nothing(self):
        paused = S.join(["Paused", "vlc", "Movie", "", "", "", ""])
        data = media.parse_playerctl(paused)
        self.assertEqual((data["status"], data["app"], data["position"], data["duration"]),
                         ("paused", "VLC", None, None))
        self.assertIsNone(media.parse_playerctl(""))
        self.assertIsNone(media.parse_playerctl(None))
        self.assertIsNone(media.parse_playerctl(S.join(["Stopped", "spotify", "Song", "", "", "", ""])))

    def test_dbus_parsing(self):
        self.assertEqual(media.parse_dbus_names(DBUS_NAMES),
                         ["org.mpris.MediaPlayer2.firefox.instance_1_84", "org.mpris.MediaPlayer2.spotify"])
        values = media.parse_dbus_properties(DBUS_PROPS)
        data = media.dbus_track("org.mpris.MediaPlayer2.spotify", values)
        self.assertEqual((data["title"], data["artist"], data["album"], data["app"]),
                         ('Song "Quoted" Title', "Band, Guest", "Album", "Spotify"))
        self.assertEqual((data["status"], data["position"], data["duration"]), ("playing", 61.5, 215))
        self.assertIsNone(media.dbus_track("org.mpris.MediaPlayer2.x", media.parse_dbus_properties("")))

    def test_backend_with_playerctl(self):
        line = S.join(["Playing", "spotify", "Song", "Band", "Album", "1000000", "215000000"])
        with mock.patch.object(media, "_find", side_effect=lambda name, *a: "/usr/bin/" + name), \
                mock.patch.object(media, "_run", return_value=line) as run:
            backend = media.LinuxMedia()
            self.assertTrue(backend.available())
            self.assertEqual(backend.read()["title"], "Song")
        self.assertIn("--all-players", run.call_args[0][0])

    def test_backend_with_dbus_send(self):
        def run(args, timeout=2.0):
            return DBUS_NAMES if "org.freedesktop.DBus.ListNames" in args else DBUS_PROPS

        tools = {"dbus-send": "/usr/bin/dbus-send"}
        with mock.patch.object(media, "_find", side_effect=lambda name, *a: tools.get(name)), \
                mock.patch.object(media, "_run", side_effect=run):
            backend = media.LinuxMedia()
            self.assertEqual(backend.read()["artist"], "Band, Guest")

    def test_no_tools(self):
        with mock.patch.object(media, "_find", return_value=None):
            self.assertEqual(MediaSource(media.LinuxMedia()).read(), {"available": False})


class MacTest(unittest.TestCase):
    def test_media_control(self):
        text = ('{"bundleIdentifier":"com.spotify.client","playing":true,"title":"Song","artist":"Band",'
                '"album":"Album","duration":215.2,"elapsedTime":60,"elapsedTimeNow":61.53,'
                '"timestamp":"2026-01-01T12:00:00Z"}')
        data = media.parse_media_control(text)
        self.assertEqual(set(data), PLAYING_KEYS)
        self.assertEqual((data["app"], data["status"], data["position"], data["duration"]),
                         ("Spotify", "playing", 61.5, 215.2))
        paused = media.parse_media_control('{"bundleIdentifier":"com.apple.WebKit.GPU",'
                                           '"parentApplicationBundleIdentifier":"com.apple.Safari",'
                                           '"playing":false,"title":"Video","elapsedTime":5,"duration":50}')
        self.assertEqual((paused["app"], paused["status"], paused["position"]), ("Safari", "paused", 5))
        for empty in ("null", "", "not json", "[]", None):
            self.assertIsNone(media.parse_media_control(empty))

    def test_nowplaying_cli(self):
        data = media.parse_nowplaying("Song\nBand\nAlbum\n215.2\n61.5\n1\n")
        self.assertEqual((data["title"], data["status"], data["position"], data["duration"]),
                         ("Song", "playing", 61.5, 215.2))
        self.assertEqual(media.parse_nowplaying("Song\nnull\nnull\nnull\nnull\n0\n")["status"], "paused")
        self.assertIsNone(media.parse_nowplaying("null\nnull\nnull\nnull\nnull\nnull\n"))
        self.assertIsNone(media.parse_nowplaying(""))

    def test_backend_prefers_media_control(self):
        tools = {"media-control": "/opt/homebrew/bin/media-control", "nowplaying-cli": "/opt/homebrew/bin/nowplaying-cli"}
        with mock.patch.object(media, "_find", side_effect=lambda name, *a: tools.get(name)), \
                mock.patch.object(media, "_run", return_value="null") as run:
            backend = media.MacMedia()
            self.assertIsNone(backend.read())
        self.assertEqual(run.call_args[0][0][:2], ["/opt/homebrew/bin/media-control", "get"])


class PlatformTest(unittest.TestCase):
    def test_backend_per_platform(self):
        with mock.patch.object(media, "_find", return_value=None):
            self.assertIsInstance(media.default_backend("win32"), media.WindowsMedia)
            self.assertIsInstance(media.default_backend("linux"), media.LinuxMedia)
            self.assertIsInstance(media.default_backend("darwin"), media.MacMedia)
            self.assertIsNone(media.default_backend("plan9"))


if __name__ == "__main__":
    unittest.main()
