"""Gemini CLI: tokens and sessions from its chat files (built here the way Gemini CLI writes them)."""

import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

from sparescreen.claude import model_label
from sparescreen.gemini import SETTLE, GeminiSource


def _iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace("+00:00", "Z")


def _tokens(inp, cached, out, thoughts=0):
    return {"input": inp, "output": out, "cached": cached, "thoughts": thoughts, "tool": 0,
            "total": inp + out + thoughts}


class GeminiSourceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        midnight = datetime.combine(datetime.now().date(), datetime.min.time()).timestamp()
        self.t = max(time.time() - 120, midnight + 1)  # safely "today"
        self.chats = self.home / "tmp" / "login-app" / "chats"
        self.chats.mkdir(parents=True)
        (self.home / "projects.json").write_text(json.dumps({"projects": {"/work/login-app": "login-app"}}))
        self.file = self.chats / "session-2026-10-25T10-00-abcd1234.jsonl"
        self.source = GeminiSource(home=self.home, refresh=0)

    def tearDown(self):
        self.tmp.cleanup()

    def message(self, id, kind, content="", offset=0, **extra):
        return dict({"id": id, "timestamp": _iso(self.t + offset), "type": kind, "content": content}, **extra)

    def write(self, *records, path=None, mode="a"):
        with open(path or self.file, mode, encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record) + "\n")

    def full_session(self):
        answer = self.message("g1", "gemini", "Looking at the login code.", 1, model="gemini-2.5-pro")
        with_tokens = dict(answer, tokens=_tokens(1000, 600, 200, thoughts=50))
        self.write(
            {"sessionId": "s1", "projectHash": "h", "startTime": _iso(self.t), "lastUpdated": _iso(self.t)},
            self.message("u1", "user", [{"text": "Fix the  login bug"}]),
            dict(answer, tokens=None),
            with_tokens,  # the same message again, now with its tokens
            dict(with_tokens, toolCalls=[{"id": "c1", "name": "read_file", "status": "success"}]),
            {"$set": {"lastUpdated": _iso(self.t + 2)}},
            self.message("g2", "gemini", "Fixed.", 3, model="gemini-2.5-flash", tokens=_tokens(1500, 1000, 100)),
            {"$set": {"summary": "Fix login bug"}},
        )

    def test_tokens_once_per_message(self):
        self.full_session()
        today = self.source.read()["today"]
        self.assertEqual(today["input"], (1000 - 600) + (1500 - 1000))  # input includes the cached part
        self.assertEqual(today["output"], 250 + 100)  # thinking counts as output
        self.assertEqual(today["cache_read"], 1600)
        self.assertEqual(today["responses"], 2)
        self.assertEqual(today["models"], {"gemini-2.5-pro": 1, "gemini-2.5-flash": 1})
        week = self.source.read()["week_models"]
        self.assertEqual(week[0]["label"], "Gemini 2.5 Flash")

    def test_rewritten_or_converted_files_are_not_counted_twice(self):
        self.full_session()
        before = self.source.read()["today"]
        lines = self.file.read_text().splitlines()
        self.file.write_text("\n".join(lines[:5]) + "\n")  # a resumed session writes the file again, shorter
        self.write({"sessionId": "s1", "messages": [json.loads(line) for line in lines[1:]
                                                     if '"type"' in line]},
                   path=self.chats / "session-old.json", mode="w")  # the old .json copy left behind
        self.assertEqual(self.source.read()["today"], before)

    def test_session_name_project_and_status(self):
        self.write({"sessionId": "s1"}, self.message("u1", "user", "Fix the login bug"))
        (session,) = self.source.read()["sessions"]
        self.assertEqual((session["name"], session["project"], session["status"]),
                         ("Fix the login bug", "login-app", "busy"))
        self.assertEqual(session["id"], "gemini:s1")

        self.write(self.message("g1", "gemini", [{"functionCall": {"name": "read_file"}}], 1))
        self.assertEqual(self.source.read()["sessions"][0]["status"], "busy")  # tools asked for: still working

        self.write(self.message("g2", "gemini", "Fixed it.", 2), {"$set": {"summary": "Fix login bug"}})
        session = self.source.read()["sessions"][0]
        self.assertEqual(session["name"], "Fix login bug")
        self.assertEqual(session["status"], "busy")  # text only, but tools may still be running
        old = time.time() - SETTLE - 5
        os.utime(self.file, (old, old))
        self.assertEqual(self.source.read()["sessions"][0]["status"], "idle")

    def test_commands_and_cancelled_requests(self):
        self.write({"sessionId": "s1"}, self.message("u0", "user", "/stats"))
        self.assertEqual(self.source.read()["sessions"], [])  # nothing asked yet
        self.write(self.message("u1", "user", "Refactor the parser", 1),
                   self.message("i1", "info", "Request cancelled.", 2))
        (session,) = self.source.read()["sessions"]
        self.assertEqual((session["name"], session["status"]), ("Refactor the parser", "idle"))

    def test_subagents_count_but_are_not_listed(self):
        self.full_session()
        sub = self.chats / "s1"
        sub.mkdir()
        self.write({"sessionId": "sub-1", "kind": "subagent"},
                   self.message("g9", "gemini", "Found 3 files.", 4, model="gemini-2.5-flash",
                                tokens=_tokens(100, 0, 10)), path=sub / "sub-1.jsonl")
        data = self.source.read()
        self.assertEqual(data["today"]["responses"], 3)
        self.assertEqual(len(data["sessions"]), 1)

    def test_old_hash_folders_and_old_json_files(self):
        old = self.home / "tmp" / ("a1" * 32) / "chats"
        old.mkdir(parents=True)
        self.write({"sessionId": "s2", "messages": [
            self.message("u5", "user", "Explain this regex"),
            self.message("g5", "gemini", "It matches dates.", 1, model="gemini-2.5-pro", tokens=_tokens(300, 0, 40)),
        ]}, path=old / "session-2026-10-20T09-00-s2.json", mode="w")
        data = self.source.read()
        self.assertEqual(data["today"]["output"], 40)
        (session,) = data["sessions"]
        self.assertEqual((session["name"], session["project"]), ("Explain this regex", ""))

    def test_reads_new_lines_only_and_survives_bad_ones(self):
        self.write({"sessionId": "s1"}, self.message("u1", "user", "Hi"))
        self.source.read()
        with open(self.file, "a", encoding="utf-8") as f:
            f.write("not json\n[1, 2]\n")
            f.write(json.dumps(self.message("g1", "gemini", "Hello", 1, tokens={"input": "lots"})) + "\n")
            f.write(json.dumps(self.message("g2", "gemini", "Again", 2, tokens=_tokens(10, 0, 5))) + "\n")
            f.write('{"half": ')  # still being written
        self.assertEqual(self.source.read()["today"]["output"], 5)

    def test_not_installed(self):
        self.assertEqual(GeminiSource(home=self.home / "nowhere").read(), {"installed": False})

    def test_model_labels(self):
        self.assertEqual(model_label("gemini-2.5-flash-lite"), "Gemini 2.5 Flash Lite")
        self.assertEqual(model_label("gemini-3-pro-preview"), "Gemini 3 Pro Preview")
        self.assertEqual(model_label("claude-opus-5-5"), "Opus 5.5")


if __name__ == "__main__":
    unittest.main()
