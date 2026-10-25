import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from sparescreen import claude

DAY = 24 * 3600


def _iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace("+00:00", "Z")


def _assistant(epoch, msg_id, model="claude-opus-test", output=100, request="req"):
    return json.dumps({
        "type": "assistant",
        "timestamp": _iso(epoch),
        "requestId": request,
        "message": {"id": msg_id, "model": model, "usage": {
            "input_tokens": 10, "cache_creation_input_tokens": 5,
            "cache_read_input_tokens": 1000, "output_tokens": output,
        }},
    })


class ClaudeSourceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        (self.home / "sessions").mkdir()
        (self.home / "projects" / "demo").mkdir(parents=True)
        now = time.time()
        midnight = datetime.combine(datetime.now().date(), datetime.min.time()).timestamp()
        today = max(now - 60, midnight + 1)  # safely "today", even right after midnight
        lines = [
            _assistant(today, "m1"),
            _assistant(today, "m1"),  # same response written twice: counted once
            _assistant(today, "m2", output=50),
            _assistant(now - 2 * DAY, "m3", model="claude-fable-test", output=7),
            _assistant(now - 10 * DAY, "m4"),  # older than what is kept
            _assistant(today, "m5", model="<synthetic>"),
            json.dumps({"type": "user", "timestamp": _iso(today), "message": {"content": "hi"}}),
        ]
        partial = _assistant(today, "m6")[:40]  # still being written: must be ignored
        (self.home / "projects" / "demo" / "s.jsonl").write_text("\n".join(lines) + "\n" + partial,
                                                                  encoding="utf-8")
        self.now = now

    def tearDown(self):
        self.tmp.cleanup()

    def source(self, limits=None):
        src = claude.ClaudeSource(home=self.home)
        patcher = mock.patch.object(claude, "load_limits", return_value=limits)
        patcher.start()
        self.addCleanup(patcher.stop)
        return src

    def test_tokens_today_dedupe_and_skip_noise(self):
        today = self.source().read()["today"]
        self.assertEqual(today["responses"], 2)
        self.assertEqual(today["output"], 150)
        self.assertEqual(today["input"], 30)
        self.assertEqual(today["cache_read"], 2000)
        self.assertEqual(today["models"], {"claude-opus-test": 2})

    def test_week_models_use_the_weekly_window(self):
        limits = {"updated_at": self.now,
                  "rate_limits": {"seven_day": {"used_percentage": 40, "resets_at": self.now + 2 * DAY}}}
        models = {m["model"]: m for m in self.source(limits).read()["week_models"]}
        self.assertEqual(set(models), {"claude-opus-test", "claude-fable-test"})
        self.assertEqual(models["claude-fable-test"]["tokens"], 10 + 5 + 1000 + 7)

    def test_limits_and_renewed_windows(self):
        saved = {"updated_at": self.now - 30, "rate_limits": {
            "seven_day": {"used_percentage": 80, "resets_at": self.now - 10},
            "five_hour": {"used_percentage": 23.5, "resets_at": self.now + 3600},
        }}
        data = self.source(saved).read()
        five, week = data["limits"]  # 5 hours first
        self.assertEqual((five["label"], five["percent"], five["renewed"], five["weekly"]), ("5 hours", 23.5, False, False))
        self.assertEqual((week["label"], week["percent"], week["renewed"], week["weekly"]), ("Week", None, True, True))
        self.assertEqual(data["limits_updated"], self.now - 30)
        self.assertIsNone(data["limits_hint"])

    def test_no_limits_file(self):
        data = self.source(None).read()
        self.assertEqual(data["limits"], [])
        self.assertIn("Check Claude limits", data["limits_hint"])

    def test_not_installed(self):
        self.assertEqual(claude.ClaudeSource(home=self.home / "missing").read(), {"installed": False})

    def test_labels(self):
        self.assertEqual(claude.model_label("claude-opus-5-5"), "Opus 5.5")
        self.assertEqual(claude.model_label("gpt-5-codex"), "gpt-5-codex")
        self.assertEqual(claude.window_label(299), "5 hours")
        self.assertEqual(claude.window_label(10079), "Week")
        self.assertEqual(claude.window_label(1440), "1 day")

    def test_open_sessions_skip_closed_processes(self):
        live, dead = os.getpid(), os.getpid() + 1
        for pid, status in ((live, "busy"), (dead, "idle")):
            (self.home / "sessions" / f"{pid}.json").write_text(json.dumps({
                "pid": pid, "sessionId": f"s{pid}", "cwd": "/work/my-project",
                "name": "Example session", "status": status, "statusUpdatedAt": self.now * 1000,
            }), encoding="utf-8")
        (self.home / "sessions" / "broken.json").write_text("{not json", encoding="utf-8")
        with mock.patch.object(claude.psutil, "pid_exists", side_effect=lambda pid: pid == live):
            sessions = self.source().read()["sessions"]
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["id"], f"s{live}")
        self.assertEqual(sessions[0]["project"], "my-project")
        self.assertEqual(sessions[0]["status"], "busy")


if __name__ == "__main__":
    unittest.main()
