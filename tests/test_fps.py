"""Game FPS: frame statistics, PresentMon's lifecycle and setup (no real PresentMon or ETW)."""

import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sparescreen import fps, panel


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class FrameStatsTest(unittest.TestCase):
    def test_fps_low_and_frametime(self):
        clock = Clock()
        stats = fps.FrameStats(window=10, now=clock)
        for i in range(600):  # 600 frames over ~5 s: mostly 8 ms, a few 20 ms stutters
            clock.t += 0.008
            stats.add(20.0 if i % 100 == 0 else 8.0)
        summary = stats.summary()
        self.assertEqual(summary["fps"], 123)        # 1000 / ~8.1 ms over the last 4 s
        self.assertEqual(summary["low1"], 50)        # the slowest 1%: the 20 ms frames
        self.assertAlmostEqual(summary["frametime"], 8.1, places=1)

    def test_old_frames_and_nonsense_are_dropped(self):
        clock = Clock()
        stats = fps.FrameStats(window=10, now=clock)
        stats.add(16.0)
        stats.add(0)
        stats.add(60000)  # a loading screen, not a frame
        clock.t += 5  # nothing in the last few seconds
        self.assertIsNone(stats.summary())

    def test_frame_column(self):
        self.assertEqual(fps.frame_column(["Application", "ProcessID", "MsBetweenPresents"]), 2)
        self.assertEqual(fps.frame_column(["Application", "FrameTime"]), 1)
        self.assertIsNone(fps.frame_column(["Application"]))


class FakeActivity:
    def __init__(self, game=None):
        self.game = game

    def read(self):
        return {"game": self.game}


class FakePresentMon:
    """Stands in for subprocess.Popen: writes the CSV PresentMon would, then the capture stops."""

    def __init__(self, rows, stopped=None):
        self.rows, self.stopped, self.calls = rows, stopped, []

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        if len(self.calls) > 1 and self.stopped:
            self.stopped.set()  # the game closed while recording the second stretch
        Path(args[args.index("--output_file") + 1]).write_text(
            "﻿Application,ProcessID,MsBetweenPresents\n" + self.rows, encoding="utf-8")
        proc = mock.Mock(args=args, returncode=0)
        proc.communicate.return_value = (None, b"")
        proc.poll.return_value = None
        return proc


class FpsSourceTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(fps.sys, "platform", "win32")
        patcher.start()
        self.addCleanup(patcher.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        tools = mock.patch.object(fps, "TOOLS", Path(tmp.name))
        tools.start()
        self.addCleanup(tools.stop)

    def test_records_stretches_of_the_game(self):
        source = fps.FpsSource(FakeActivity())
        stats, stopped = fps.FrameStats(), fps.threading.Event()
        popen = FakePresentMon("game.exe,1234,10.0\n" * 50 + "game.exe,1234,NA\n", stopped)
        with mock.patch.object(fps.subprocess, "Popen", popen):
            source._capture("PresentMon.exe", 1234, stats, stopped)
        self.assertIn("1234", popen.calls[0])
        self.assertNotIn("--no_track_display", popen.calls[0])  # with it, PresentMon writes nothing
        self.assertEqual((stats.summary()["fps"], stats.summary()["frametime"]), (100, 10.0))
        self.assertEqual(list(fps.TOOLS.glob("*.csv")), [])  # its file is cleaned up

    def test_starts_and_stops_with_the_game(self):
        activity = FakeActivity({"name": "Game", "pid": 1234})
        source = fps.FpsSource(activity)
        with mock.patch.object(fps, "find_presentmon", return_value="PresentMon.exe"), \
                mock.patch.object(fps, "allowed", return_value=True), \
                mock.patch.object(fps.threading, "Thread") as thread, \
                mock.patch.object(fps.subprocess, "run") as run:
            self.assertTrue(source.read()["playing"])
            thread.assert_called_once()
            source._proc = mock.Mock(args=["PresentMon.exe"], poll=mock.Mock(return_value=None))
            proc = source._proc
            activity.game = None  # the game closed: PresentMon stops and its session is closed
            self.assertEqual(source.read(), {"available": True, "playing": False})
        proc.terminate.assert_called_once()
        self.assertIn("--terminate_existing_session", run.call_args[0][0])

    def test_presentmon_output_as_it_really_comes(self):
        # A real line from PresentMon 2.6 (Minecraft, OpenGL shows up as "Other").
        text = ("Application,ProcessID,SwapChainAddress,PresentRuntime,SyncInterval,PresentFlags,"
                "AllowsTearing,PresentMode,TimeInMs,MsBetweenSimulationStart,MsBetweenPresents\n"
                "javaw.exe,22184,0x0,Other,0,0,1,Hardware: Legacy Flip,6.9949,NA,2.67300000000000\n")
        self.assertEqual(fps.frame_times(text), [2.673])

    def test_needs_setup_or_permission(self):
        source = fps.FpsSource(FakeActivity({"name": "Game", "pid": 1}))
        with mock.patch.object(fps, "find_presentmon", return_value=None):
            self.assertEqual(source.read()["error"], "setup")
        source = fps.FpsSource(FakeActivity({"name": "Game", "pid": 2}))
        with mock.patch.object(fps, "find_presentmon", return_value="PresentMon.exe"), \
                mock.patch.object(fps, "allowed", return_value=False):
            self.assertEqual(source.read()["error"], "permission")

    def test_other_systems(self):
        with mock.patch.object(fps.sys, "platform", "linux"):
            self.assertEqual(fps.FpsSource(FakeActivity()).read(), {"available": False})


class SetupTest(unittest.TestCase):
    def test_download_keeps_only_the_published_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "PresentMon.exe"
            with mock.patch.multiple(fps, TOOLS=Path(tmp), EXE=exe), \
                    mock.patch.object(fps.urllib.request, "urlopen", return_value=io.BytesIO(b"tampered")):
                self.assertIn("checksum", fps.download())
            self.assertFalse(exe.exists())
            good = b"the real thing"
            with mock.patch.multiple(fps, TOOLS=Path(tmp), EXE=exe, SHA256=hashlib.sha256(good).hexdigest()), \
                    mock.patch.object(fps.urllib.request, "urlopen", return_value=io.BytesIO(good)):
                self.assertIsNone(fps.download())
            self.assertEqual(exe.read_bytes(), good)

    def test_panel_states(self):
        with mock.patch.object(panel.sys, "platform", "win32"), \
                mock.patch.object(fps, "find_presentmon", return_value=None), \
                mock.patch.object(fps, "requested", return_value=False):
            check = panel.Panel()._fps_check({})
        self.assertEqual((check["status"], check["action"]["id"]), ("info", "fps_enable"))
        with mock.patch.object(panel.sys, "platform", "win32"), \
                mock.patch.object(fps, "find_presentmon", return_value="pm.exe"), \
                mock.patch.object(fps, "allowed", return_value=False), \
                mock.patch.object(fps, "requested", return_value=True):
            self.assertIn("Sign out", panel.Panel()._fps_check({})["detail"])
        with mock.patch.object(panel.sys, "platform", "win32"), \
                mock.patch.object(fps, "find_presentmon", return_value="pm.exe"), \
                mock.patch.object(fps, "allowed", return_value=True):
            check = panel.Panel()._fps_check({"fps": {"playing": True, "fps": 144}})
        self.assertEqual((check["status"], check["detail"]), ("ok", "144 FPS right now"))
        with mock.patch.object(panel.sys, "platform", "linux"):
            self.assertIsNone(panel.Panel()._fps_check({}))


if __name__ == "__main__":
    unittest.main()
