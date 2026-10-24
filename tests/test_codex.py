import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

from sparescreen.codex import CodexSource


def _iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace("+00:00", "Z")


def _line(epoch, kind, payload):
    return json.dumps({"timestamp": _iso(epoch), "type": kind, "payload": payload})


def _tokens(epoch, inp, cached, out, rate_limits=None):
    payload = {"type": "token_count", "info": {"total_token_usage": {
        "input_tokens": inp, "cached_input_tokens": cached, "output_tokens": out,
        "reasoning_output_tokens": 0, "total_tokens": inp + out}}}
    if rate_limits is not None:
        payload["rate_limits"] = rate_limits
    return _line(epoch, "event_msg", payload)


class CodexSourceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        day = self.home / "sessions" / "2026" / "10" / "24"
        day.mkdir(parents=True)
        now = time.time()
        midnight = datetime.combine(datetime.now().date(), datetime.min.time()).timestamp()
        t = max(now - 120, midnight + 1)  # safely "today"
        self.now, self.t = now, t
        limits = {
            "primary": {"used_percent": 30.0, "window_minutes": 299, "resets_at": int(now + 3600)},
            # older Codex versions sent resets_in_seconds instead of resets_at
            "secondary": {"used_percent": 60.0, "window_minutes": 10079, "resets_in_seconds": 86400},
        }
        lines = [
            _line(t, "session_meta", {"id": "abc-123", "cwd": "/work/parser-lib", "cli_version": "0.0.0"}),
            _line(t, "turn_context", {"model": "gpt-test-codex", "cwd": "/work/parser-lib"}),
            _line(t, "event_msg", {"type": "user_message", "message": "Refactor   the parser\nplease"}),
            _line(t, "event_msg", {"type": "turn_started"}),
            _tokens(t + 1, 1000, 600, 200, limits),
            _tokens(t + 2, 1500, 800, 300),          # cumulative: this adds 500/200/100
            _line(t + 3, "event_msg", {"type": "turn_complete"}),
        ]
        (day / "rollout-2026-10-24T10-00-00-abc-123.jsonl").write_text(
            "\n".join(lines) + "\n" + _tokens(t + 4, 9000, 0, 0)[:30], encoding="utf-8")  # half-written line

        # A session that was closed mid-turn a while ago: shown as idle, not working.
        stale = day / "rollout-2026-10-24T08-00-00-def-456.jsonl"
        stale.write_text("\n".join([
            _line(now - 7200, "session_meta", {"id": "def-456", "cwd": "/work/site"}),
            _line(now - 7200, "event_msg", {"type": "task_started"}),
        ]) + "\n", encoding="utf-8")
        os.utime(stale, (now - 7200, now - 7200))

    def tearDown(self):
        self.tmp.cleanup()

    def test_tokens_today_from_cumulative_totals(self):
        today = CodexSource(home=self.home).read()["today"]
        self.assertEqual(today["input"], (1000 - 600) + (500 - 200))  # cached part counted separately
        self.assertEqual(today["cache_read"], 800)
        self.assertEqual(today["output"], 300)
        self.assertEqual(today["responses"], 2)
        self.assertEqual(today["models"], {"gpt-test-codex": 2})

    def test_limits(self):
        data = CodexSource(home=self.home).read()
        five, week = data["limits"]
        self.assertEqual((five["label"], five["percent"], five["weekly"]), ("5 hours", 30.0, False))
        self.assertEqual((week["label"], week["percent"], week["weekly"]), ("Week", 60.0, True))
        self.assertAlmostEqual(week["resets_at"], self.t + 1 + 86400, delta=1)
        self.assertAlmostEqual(data["limits_updated"], self.t + 1, delta=1)
        self.assertEqual(data["week_models"][0]["model"], "gpt-test-codex")

    def test_sessions(self):
        sessions = {s["id"]: s for s in CodexSource(home=self.home).read()["sessions"]}
        main = sessions["codex:abc-123"]
        self.assertEqual(main["name"], "Refactor the parser please")
        self.assertEqual(main["project"], "parser-lib")
        self.assertEqual(main["status"], "idle")  # turn_complete came after turn_started
        self.assertEqual(sessions["codex:def-456"]["status"], "idle")  # stale turn

    def test_working_session(self):
        path = next((self.home / "sessions").rglob("rollout-*abc-123.jsonl"))
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n" + _line(time.time(), "event_msg", {"type": "turn_started"}) + "\n")
        sessions = {s["id"]: s for s in CodexSource(home=self.home).read()["sessions"]}
        self.assertEqual(sessions["codex:abc-123"]["status"], "busy")

    def test_not_installed(self):
        self.assertEqual(CodexSource(home=self.home / "missing").read(), {"installed": False})

    def test_no_limits_yet(self):
        empty = self.home / "empty"
        (empty / "sessions").mkdir(parents=True)
        data = CodexSource(home=empty).read()
        self.assertEqual(data["limits"], [])
        self.assertTrue(data["limits_hint"])
        self.assertEqual(data["sessions"], [])


if __name__ == "__main__":
    unittest.main()
