import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from sparescreen import claude, claude_probe
from sparescreen.claude_probe import LimitsProbe, limits_from_event

EVENT = {"type": "rate_limit_event", "rate_limit_info": {
    "status": "allowed", "rateLimitType": "five_hour",
    "unifiedWindows": {
        "five_hour": {"utilization": 0.19, "resetsAt": 1792893600, "status": "allowed"},
        "seven_day": {"utilization": 0.59, "resetsAt": 1792936800, "status": "allowed"},
        "seven_day_opus": {"utilization": 0.4, "resetsAt": 1792936800, "status": "allowed"},
    }}}


class EventParsingTest(unittest.TestCase):
    def test_limits_from_event(self):
        limits = limits_from_event(EVENT)
        self.assertEqual(limits["five_hour"], {"used_percentage": 19.0, "resets_at": 1792893600})
        self.assertEqual(limits["seven_day"]["used_percentage"], 59.0)
        self.assertIn("seven_day_opus", limits)
        self.assertEqual(limits_from_event({"type": "rate_limit_event"}), {})

    def test_labels_for_limit_keys(self):
        self.assertEqual(claude.limit_label("five_hour"), ("5 hours", False))
        self.assertEqual(claude.limit_label("seven_day"), ("Week", True))
        self.assertEqual(claude.limit_label("seven_day_opus"), ("Week · Opus", True))
        self.assertIsNone(claude.limit_label("something_else"))


class ProbeGatingTest(unittest.TestCase):
    def probe(self):
        p = LimitsProbe(exe="claude")
        p._run = mock.Mock()  # don't start real threads/processes
        return p

    def started(self, p, active, updated_at):
        with mock.patch.object(claude_probe.threading, "Thread") as thread:
            ran = p.maybe_run(active, updated_at)
        return ran and thread.called

    def test_runs_only_while_claude_is_in_use(self):
        self.assertFalse(self.started(self.probe(), active=False, updated_at=None))
        self.assertTrue(self.started(self.probe(), active=True, updated_at=None))

    def test_skips_when_numbers_are_fresh(self):
        self.assertFalse(self.started(self.probe(), active=True, updated_at=time.time() - 60))
        self.assertTrue(self.started(self.probe(), active=True, updated_at=time.time() - 3600))

    def test_waits_between_attempts_and_needs_the_command(self):
        p = self.probe()
        self.assertTrue(self.started(p, True, None))
        p._running = False
        self.assertFalse(self.started(p, True, None))  # tried less than `interval` ago
        self.assertFalse(self.started(LimitsProbe(exe=""), True, None))


class ProbeRunTest(unittest.TestCase):
    def run_with(self, stdout):
        done = subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")
        p = LimitsProbe(exe="claude")
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(claude_probe, "PROBE_DIR", Path(tmp) / "probe"), \
                mock.patch.object(claude_probe.subprocess, "run", return_value=done) as run, \
                mock.patch.object(claude_probe, "save_limits") as save:
            p._run()
        return p, run, save

    def test_saves_limits_from_the_stream(self):
        stream = "\n".join([json.dumps({"type": "system", "subtype": "init"}), json.dumps(EVENT),
                            "not json", json.dumps({"type": "result"})])
        p, run, save = self.run_with(stream)
        save.assert_called_once()
        self.assertEqual(save.call_args[0][0]["five_hour"]["used_percentage"], 19.0)
        self.assertIsNone(p.last_error)
        args = run.call_args[0][0]
        self.assertIn("--no-session-persistence", args)  # leaves no history behind
        self.assertIn("haiku", args)

    def test_no_event(self):
        p, _, save = self.run_with(json.dumps({"type": "result"}))
        save.assert_not_called()
        self.assertTrue(p.last_error)


class ClaudeSourceWithProbeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        (self.home / "sessions").mkdir()
        for pid, cwd in ((os.getpid(), "/work/app"), (os.getpid() + 1, str(claude_probe.PROBE_DIR))):
            (self.home / "sessions" / f"{pid}.json").write_text(json.dumps({
                "pid": pid, "sessionId": f"s{pid}", "cwd": cwd, "status": "busy",
                "statusUpdatedAt": time.time() * 1000}), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def read(self, enabled, probe):
        src = claude.ClaudeSource(home=self.home, probe=probe, probe_enabled=lambda: enabled)
        with mock.patch.object(claude, "load_limits", return_value=None), \
                mock.patch.object(claude.psutil, "pid_exists", return_value=True):
            return src.read()

    def test_probe_session_is_hidden_and_probe_runs_when_enabled(self):
        probe = mock.Mock(available=True)
        data = self.read(True, probe)
        self.assertEqual([s["project"] for s in data["sessions"]], ["app"])
        probe.maybe_run.assert_called_once()
        self.assertTrue(probe.maybe_run.call_args[0][0])  # a busy session means "in use"
        self.assertIn("Checking", data["limits_hint"])

    def test_disabled_probe_is_left_alone(self):
        probe = mock.Mock(available=True)
        data = self.read(False, probe)
        probe.maybe_run.assert_not_called()
        self.assertIn("settings", data["limits_hint"])

    def test_missing_command_hint(self):
        data = self.read(True, mock.Mock(available=False))
        self.assertIn("not found", data["limits_hint"])


if __name__ == "__main__":
    unittest.main()
