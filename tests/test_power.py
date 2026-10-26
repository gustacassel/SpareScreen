"""The PC going to sleep: the "asleep" flag, the notice to the phone and the USB screen."""

import io
import threading
import time
import unittest
from unittest import mock

from sparescreen import power
from tests.test_usb import FakeAdbBridge


class PowerWatchTest(unittest.TestCase):
    def test_asleep_until_woken(self):
        watch = power.PowerWatch()
        self.assertEqual(watch.read(), {"asleep": False})
        watch.going_to_sleep()
        self.assertEqual(watch.read(), {"asleep": True})
        watch.woke_up()
        self.assertFalse(watch.asleep())

    def test_clears_itself_after_waking_without_notice(self):
        watch = power.PowerWatch()
        watch.going_to_sleep()
        watch.asleep_at -= power.STALE + 1  # the clock jumped: hours went by asleep
        self.assertFalse(watch.asleep())

    def test_tells_the_phone_without_holding_up_the_sleep(self):
        watch = power.PowerWatch()
        told = threading.Event()
        stuck = threading.Event()

        def on_sleep():
            told.set()
            stuck.wait(5)  # a phone that doesn't answer

        watch.on_sleep = on_sleep
        start = time.monotonic()
        with mock.patch.object(power, "GRACE", 0.2):
            watch.going_to_sleep()
        self.assertTrue(told.is_set())
        self.assertLess(time.monotonic() - start, 2)
        stuck.set()

    def test_linux_reads_logind(self):
        lines = ["/org/freedesktop/login1: org.freedesktop.login1.Manager.PrepareForSleep (true,)\n"]
        process = mock.Mock(stdout=io.StringIO("".join(lines)))
        watch = power.PowerWatch()
        with mock.patch.object(power.sys, "platform", "linux"), \
                mock.patch.object(power.shutil, "which", return_value="/usr/bin/gdbus"), \
                mock.patch.object(power.subprocess, "Popen", return_value=process), \
                mock.patch.object(power.threading, "Thread") as thread, \
                mock.patch.object(power.atexit, "register"):
            watch.start()
        thread.call_args[1]["target"]()  # read the lines here instead of on a thread
        self.assertTrue(watch.asleep())

    def test_linux_without_gdbus(self):
        watch = power.PowerWatch()
        with mock.patch.object(power.sys, "platform", "linux"), \
                mock.patch.object(power.shutil, "which", return_value=None), \
                mock.patch.object(power.subprocess, "Popen") as popen:
            watch.start()
        popen.assert_not_called()

    def test_start_never_raises(self):
        watch = power.PowerWatch()
        with mock.patch.object(power.sys, "platform", "win32"), \
                mock.patch.object(watch, "_start_windows", side_effect=OSError("no powrprof")):
            watch.start()  # just prints; the phone falls back to "Disconnected"


class RestNowTest(unittest.TestCase):
    def test_rests_the_usb_phone_right_away(self):
        bridge = FakeAdbBridge()
        bridge._poll()  # the phone is known, nothing to rest yet
        bridge.screen = lambda: "off"
        bridge.rest_screens()
        self.assertIn(("-s", "SER1", "shell", "input", "keyevent", "KEYCODE_SLEEP"), bridge.calls)


if __name__ == "__main__":
    unittest.main()
