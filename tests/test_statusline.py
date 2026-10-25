import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sparescreen import statusline

DATA = {"model": {"display_name": "Opus"},
        "rate_limits": {"five_hour": {"used_percentage": 30, "resets_at": 1}}}
RAW = json.dumps(DATA).encode("utf-8")


def fake_popen(out=b"", code=0, error=None):
    proc = mock.Mock(returncode=code)
    if error:
        proc.communicate.side_effect = error
    else:
        proc.communicate.return_value = (out, None)
    return mock.Mock(return_value=proc), proc


class StatusLineTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.limits_file = Path(tmp.name) / "limits.json"
        for patcher in (mock.patch.object(statusline, "LIMITS_FILE", self.limits_file),
                        mock.patch.dict(os.environ)):
            patcher.start()
            self.addCleanup(patcher.stop)
        os.environ.pop(statusline.WRAP_ENV, None)

    def run_main(self, argv, raw=RAW):
        stdin = io.TextIOWrapper(io.BytesIO(raw))
        stdout = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        with mock.patch.object(sys, "stdin", stdin), mock.patch.object(sys, "stdout", stdout):
            code = statusline.main(argv)
            stdout.flush()
            return code, stdout.buffer.getvalue()

    def saved(self):
        return json.loads(self.limits_file.read_text(encoding="utf-8"))["rate_limits"]

    def test_no_wrap_prints_own_text(self):
        popen, _ = fake_popen()
        with mock.patch.object(subprocess, "Popen", popen):
            code, out = self.run_main([])
        self.assertIsNone(code)
        self.assertEqual(out.decode("utf-8").strip(), "Opus · 5h 30%")
        popen.assert_not_called()
        self.assertEqual(self.saved(), DATA["rate_limits"])

    def test_wrap_passes_stdin_and_output_through(self):
        popen, proc = fake_popen(b"line one\r\nline two \xe2\x9c\x93\n")
        with mock.patch.object(subprocess, "Popen", popen), \
                mock.patch.object(statusline.shutil, "which", return_value=None):
            code, out = self.run_main(["--", "bash", "~/.claude/my-status.sh"])
        self.assertEqual(code, 0)
        self.assertEqual(out, b"line one\r\nline two \xe2\x9c\x93\n")
        self.assertEqual(popen.call_args[0][0], ["bash", "~/.claude/my-status.sh"])
        self.assertFalse(popen.call_args[1]["shell"])
        self.assertNotIn(statusline.WRAP_ENV, popen.call_args[1]["env"])
        self.assertEqual(proc.communicate.call_args[0][0], RAW)
        self.assertEqual(self.saved(), DATA["rate_limits"])

    def test_wrap_from_env_uses_shell_and_keeps_exit_code(self):
        os.environ[statusline.WRAP_ENV] = "my-status | head -1"
        popen, _ = fake_popen(b"partial\n", code=3)
        with mock.patch.object(subprocess, "Popen", popen):
            code, out = self.run_main([])
        self.assertEqual((code, out), (3, b"partial\n"))
        self.assertEqual(popen.call_args[0][0], "my-status | head -1")
        self.assertTrue(popen.call_args[1]["shell"])

    def test_single_quoted_argument_runs_in_shell(self):
        with mock.patch.object(statusline.shutil, "which", return_value=None):
            self.assertEqual(statusline.wrapped_command(["--", "a | b"]), ("a | b", True))
        with mock.patch.object(statusline.shutil, "which", return_value="/bin/x"):
            self.assertEqual(statusline.wrapped_command(["--", "x"]), (["x"], False))
        self.assertIsNone(statusline.wrapped_command(["--"]))

    def test_fallback_on_timeout_failure_or_missing_command(self):
        cases = [
            fake_popen(error=subprocess.TimeoutExpired("x", 5))[0],
            fake_popen(b"", code=1)[0],
            mock.Mock(side_effect=FileNotFoundError("nope")),
        ]
        for popen in cases:
            with mock.patch.object(subprocess, "Popen", popen):
                code, out = self.run_main(["--", "bash", "status.sh"])
            self.assertIsNone(code)
            self.assertEqual(out.decode("utf-8").strip(), "Opus · 5h 30%")
            self.assertEqual(self.saved(), DATA["rate_limits"])

    def test_executable_resolved_to_full_path(self):
        # Windows needs the full path to start .cmd shims such as npx.
        found = os.path.abspath(os.path.join("node", "npx.cmd"))
        popen, _ = fake_popen(b"x\n")
        with mock.patch.object(subprocess, "Popen", popen), \
                mock.patch.object(statusline.shutil, "which", return_value=found):
            statusline.run_wrapped(["npx", "some-status"], False, b"{}")
        self.assertEqual(popen.call_args[0][0], [found, "some-status"])

    def test_timeout_kills_the_command(self):
        popen, proc = fake_popen(error=subprocess.TimeoutExpired("x", 5))
        with mock.patch.object(subprocess, "Popen", popen):
            self.run_main(["--", "bash", "status.sh"])
        proc.kill.assert_called_once()

    def test_save_errors_do_not_break_the_wrapped_line(self):
        popen, _ = fake_popen(b"mine\n")
        with mock.patch.object(subprocess, "Popen", popen), \
                mock.patch.object(statusline, "save_limits", side_effect=OSError("read-only")):
            code, out = self.run_main(["--", "bash", "status.sh"])
        self.assertEqual((code, out), (0, b"mine\n"))

    def test_bad_input_still_reaches_the_wrapped_command(self):
        popen, proc = fake_popen(b"ok\n")
        with mock.patch.object(subprocess, "Popen", popen):
            code, out = self.run_main(["--", "bash", "status.sh"], raw=b"[1, 2]")
        self.assertEqual(out, b"ok\n")
        self.assertEqual(proc.communicate.call_args[0][0], b"[1, 2]")

    def test_real_process_round_trip(self):
        script = r"import sys; d = sys.stdin.buffer.read(); sys.stdout.buffer.write(b'A\nB:' + d)"
        result = statusline.run_wrapped([sys.executable, "-c", script], False, b"{}")
        self.assertEqual(result, (b"A\nB:{}", 0))


if __name__ == "__main__":
    unittest.main()
