#!/usr/bin/env python3
"""Tests for neuros-runbook runbook verifier.

These tests do not need real container kernel delegation because they
mock subprocess.run (the call into neuros-sandbox) and the inner
_run_step helper. They assert:

  * Runbook parser accepts well-formed JSON arrays of steps.
  * Runbook parser rejects name collisions, non-string scripts, malformed
    expect.regex, etc., with a RunbookError that names the bad step.
  * _run_step surfaces stdout/stderr/exit_code from the JSON envelope.
  * Per-step assertion logic (exit_code, stdout_matches, timeout_forbidden)
    surfaces failures as a list.
  * The cmd_run dispatcher exits 0 when all steps pass, 1 on any failure.
  * --only-violations filters table output.
  * --json emits an envelope whose schema matches the documented contract.
"""
import importlib.util
import io
import json
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
_RUNBOOK_PATH = os.path.join(
    ROOT, "config", "includes.chroot", "usr", "local", "bin", "neuros-runbook")


def _load_neuros_runbook():
    """Load `neuros-runbook` (no .py suffix) by compiling + exec in a
    fresh module namespace, mirroring the loader pattern used in
    tests/test_sandbox.py and tests/test_bench.py."""
    with open(_RUNBOOK_PATH) as f:
        source = f.read()
    code = compile(source, _RUNBOOK_PATH, "exec")
    module = sys.modules.get("neuros_runbook") or types.ModuleType(
        "neuros_runbook")
    module.__file__ = _RUNBOOK_PATH
    sys.modules["neuros_runbook"] = module
    exec(code, module.__dict__)
    return module


rb = _load_neuros_runbook()


class TestRunbookLoader(unittest.TestCase):
    """Locks the runbook JSON validation contract."""

    def _write(self, content):
        f = tempfile.NamedTemporaryFile("w", delete=False, suffix=".json")
        json.dump(content, f)
        f.close()
        return f.name

    def test_well_formed_runbook_loads(self):
        path = self._write([
            {"name": "smoke", "script": "print(1)\n"},
            {"name": "fail", "script": "raise Exception\n",
             "expect": {"exit_code": 1}},
            {"name": "regex", "script": "print('hello')\n",
             "expect": {"stdout_matches": "hel+"}},
        ])
        try:
            steps = rb.load_runbook(path)
            self.assertEqual(len(steps), 3)
            self.assertEqual(steps[0]["name"], "smoke")
            self.assertEqual(steps[1]["expect"]["exit_code"], 1)
        finally:
            os.unlink(path)

    def test_duplicate_name_rejected(self):
        path = self._write([
            {"name": "x", "script": "pass\n"},
            {"name": "x", "script": "pass\n"},
        ])
        try:
            with self.assertRaises(rb.RunbookError) as cm:
                rb.load_runbook(path)
            self.assertIn("duplicate name", str(cm.exception))
        finally:
            os.unlink(path)

    def test_empty_script_rejected(self):
        path = self._write([{"name": "x", "script": ""}])
        try:
            with self.assertRaises(rb.RunbookError):
                rb.load_runbook(path)
        finally:
            os.unlink(path)

    def test_non_array_top_level_rejected(self):
        f = tempfile.NamedTemporaryFile("w", delete=False, suffix=".json")
        f.write(json.dumps({"not": "an array"}))
        f.close()
        try:
            with self.assertRaises(rb.RunbookError) as cm:
                rb.load_runbook(f.name)
            self.assertIn("must be a JSON array", str(cm.exception))
        finally:
            os.unlink(f.name)

    def test_invalid_regex_rejected_at_parse_time(self):
        path = self._write([
            {"name": "bad", "script": "pass\n",
             "expect": {"stdout_matches": "[unclosed"}},
        ])
        try:
            with self.assertRaises(rb.RunbookError) as cm:
                rb.load_runbook(path)
            self.assertIn("regex invalid", str(cm.exception))
            self.assertIn("bad", str(cm.exception))
        finally:
            os.unlink(path)

    def test_empty_name_rejected(self):
        path = self._write([{"name": "", "script": "pass\n"}])
        try:
            with self.assertRaises(rb.RunbookError):
                rb.load_runbook(path)
        finally:
            os.unlink(path)

    def test_step_must_be_object(self):
        path = self._write(["not a dict"])
        try:
            with self.assertRaises(rb.RunbookError):
                rb.load_runbook(path)
        finally:
            os.unlink(path)


class TestRunStepAndAssertions(unittest.TestCase):
    """Drive _run_step with a mocked subprocess.run so the JSON-envelope
    parsing + assertion logic both get exercised."""

    def _fake_cp(self, stdout_text, returncode=0):
        cp = mock.Mock()
        cp.stdout = stdout_text.encode()
        cp.stderr = b""
        cp.returncode = returncode
        return cp

    def test_exit_code_match(self):
        step = {"name": "x", "script": "print(1)",
                "expect": {"exit_code": 0}}
        cp = self._fake_cp(json.dumps({
            "exit_code": 0, "stdout": "1\n",
            "wall_clock_ms": 1, "timeout_hit": False,
            "peak_mem_estimate": 1024}))
        with mock.patch.object(rb.subprocess, "run", return_value=cp):
            env_obj, failures = rb._run_step(step,
                                             env={"PATH": "/bin"})
        self.assertEqual(env_obj["exit_code"], 0)
        self.assertEqual(failures, [])

    def test_exit_code_mismatch(self):
        step = {"name": "x", "script": "raise Exception",
                "expect": {"exit_code": 0}}
        cp = self._fake_cp(json.dumps({
            "exit_code": 1, "stdout": "",
            "wall_clock_ms": 1, "timeout_hit": False,
            "peak_mem_estimate": None}))
        with mock.patch.object(rb.subprocess, "run", return_value=cp):
            env_obj, failures = rb._run_step(step,
                                             env={"PATH": "/bin"})
        self.assertTrue(any("exit_code" in f for f in failures))

    def test_exit_code_any(self):
        step = {"name": "x", "script": "anything",
                "expect": {"exit_code": "any"}}
        cp = self._fake_cp(json.dumps({
            "exit_code": 137, "stdout": "",
            "wall_clock_ms": 1, "timeout_hit": False,
            "peak_mem_estimate": 100}))
        with mock.patch.object(rb.subprocess, "run", return_value=cp):
            env_obj, failures = rb._run_step(step,
                                             env={"PATH": "/bin"})
        self.assertEqual(failures, [])

    def test_stdout_pattern_mismatch(self):
        step = {"name": "x", "script": "pass",
                "expect": {"stdout_matches": "needle"}}
        cp = self._fake_cp(json.dumps({
            "exit_code": 0, "stdout": "haystack\n",
            "wall_clock_ms": 1, "timeout_hit": False,
            "peak_mem_estimate": None}))
        with mock.patch.object(rb.subprocess, "run", return_value=cp):
            _, failures = rb._run_step(step, env={"PATH": "/bin"})
        self.assertTrue(any("stdout_matches" in f for f in failures))

    def test_stderr_pattern_match(self):
        step = {"name": "x", "script": "raise Exception",
                "expect": {"stderr_matches": "Traceback"}}
        cp = self._fake_cp(json.dumps({
            "exit_code": 1, "stdout": "",
            "stderr": "Traceback (most recent call last):\n",
            "wall_clock_ms": 1, "timeout_hit": False,
            "peak_mem_estimate": None}))
        with mock.patch.object(rb.subprocess, "run", return_value=cp):
            _, failures = rb._run_step(step, env={"PATH": "/bin"})
        self.assertEqual(failures, [])

    def test_timeout_forbidden(self):
        step = {"name": "x", "script": "while True: pass",
                "expect": {"timeout_forbidden": True}}
        cp = self._fake_cp(json.dumps({
            "exit_code": 124, "stdout": "",
            "wall_clock_ms": 5000, "timeout_hit": True,
            "peak_mem_estimate": None}))
        with mock.patch.object(rb.subprocess, "run", return_value=cp):
            _, failures = rb._run_step(step, env={"PATH": "/bin"})
        self.assertTrue(any("timeout" in f for f in failures))

    def test_all_assertions_pass(self):
        step = {"name": "x", "script": "print('hello')",
                "expect": {"exit_code": 0,
                           "stdout_matches": "^hello$",
                           "stderr_matches": ".*"}}
        cp = self._fake_cp(json.dumps({
            "exit_code": 0, "stdout": "hello\n",
            "stderr": "",
            "wall_clock_ms": 2, "timeout_hit": False,
            "peak_mem_estimate": 4096}))
        with mock.patch.object(rb.subprocess, "run", return_value=cp):
            env_obj, failures = rb._run_step(step,
                                             env={"PATH": "/bin"})
        self.assertEqual(env_obj["peak_mem_estimate"], 4096)
        self.assertEqual(failures, [])


class TestCmdRunDispatch(unittest.TestCase):
    """Top-level cmd_run aggregates step results into the documented
    JSON envelope and pickes the right exit code."""

    def _write(self, content):
        f = tempfile.NamedTemporaryFile("w", delete=False, suffix=".json")
        json.dump(content, f)
        f.close()
        return f.name

    def _ok_envelope(self, exit_code=0, timeout_hit=False,
                     peak=None, wall_ms=10, stdout="", stderr=""):
        return json.dumps({
            "exit_code": exit_code, "stdout": stdout, "stderr": stderr,
            "wall_clock_ms": wall_ms, "timeout_hit": timeout_hit,
            "peak_mem_estimate": peak})

    def test_all_pass_returns_zero(self):
        path = self._write([
            {"name": "a", "script": "pass", "expect": {"exit_code": 0}},
            {"name": "b", "script": "pass", "expect": {"exit_code": 0}},
        ])
        try:
            ns = mock.MagicMock()
            ns.runbook = path
            ns.json = False
            ns.only_violations = False
            cp = mock.Mock(returncode=0,
                           stdout=self._ok_envelope().encode(),
                           stderr=b"")
            with mock.patch.object(rb.subprocess, "run", return_value=cp), \
                 mock.patch.object(sys, "stdout", io.StringIO()), \
                 mock.patch.object(sys, "stderr", io.StringIO()):
                rc = rb.cmd_run(ns)
            self.assertEqual(rc, 0)
        finally:
            os.unlink(path)

    def test_any_fail_returns_one(self):
        """Two-step runbook where step b fails its exit_code
        assertion. cmd_run should aggregate and exit 1."""
        path = self._write([
            {"name": "a", "script": "pass", "expect": {"exit_code": 0}},
            {"name": "b", "script": "raise",
             "expect": {"exit_code": 0}},
        ])
        try:
            ns = mock.MagicMock()
            ns.runbook = path
            ns.json = False
            ns.only_violations = False

            # Stream two envelopes: step a OK, step b fails.
            queue = iter([
                self._ok_envelope().encode(),
                self._ok_envelope(exit_code=1, stderr="boom").encode(),
            ])

            def fake_run(*a, **kw):
                cp = mock.Mock()
                cp.stdout = next(queue)
                cp.stderr = b""
                cp.returncode = 0
                return cp

            with (mock.patch.object(rb.subprocess, "run",
                                   side_effect=fake_run),
                  mock.patch.object(sys, "stdout", io.StringIO()),
                  mock.patch.object(sys, "stderr", io.StringIO())):
                rc = rb.cmd_run(ns)
            self.assertEqual(rc, 1)
        finally:
            os.unlink(path)

    def test_only_violations_table_filters_pass(self):
        path = self._write([
            {"name": "pass-step", "script": "pass"},
            {"name": "fail-step", "script": "raise",
             "expect": {"exit_code": 0}},
        ])
        try:
            ns = mock.MagicMock()
            ns.runbook = path
            ns.json = False
            ns.only_violations = True

            ok_env = self._ok_envelope()
            fail_env = self._ok_envelope(exit_code=1, stderr="boom")
            queue = iter([ok_env.encode(), fail_env.encode()])

            def fake_run(*a, **kw):
                cp = mock.Mock()
                cp.stdout = next(queue)
                cp.stderr = b""
                cp.returncode = 0
                return cp

            with mock.patch.object(rb.subprocess, "run",
                                   side_effect=fake_run):
                buf_out = io.StringIO()
                with mock.patch.object(sys, "stdout", buf_out), \
                     mock.patch.object(sys, "stderr", io.StringIO()):
                    rc = rb.cmd_run(ns)
            self.assertEqual(rc, 1)
            # Only fail-step should appear in the table
            self.assertIn("fail-step", buf_out.getvalue())
            self.assertNotIn("pass-step", buf_out.getvalue())
        finally:
            os.unlink(path)

    def test_json_envelope_shape(self):
        path = self._write([
            {"name": "audit-step", "script": "pass",
             "expect": {"exit_code": 0}},
        ])
        try:
            ns = mock.MagicMock()
            ns.runbook = path
            ns.json = True
            ns.only_violations = False
            queue = iter([self._ok_envelope(
                exit_code=0, peak=4096, wall_ms=2).encode()])

            def fake_run(*a, **kw):
                cp = mock.Mock()
                cp.stdout = next(queue)
                cp.stderr = b""
                cp.returncode = 0
                return cp

            with mock.patch.object(rb.subprocess, "run",
                                   side_effect=fake_run):
                buf_out = io.StringIO()
                with mock.patch.object(sys, "stdout", buf_out):
                    rc = rb.cmd_run(ns)
            self.assertEqual(rc, 0)
            env = json.loads(buf_out.getvalue())
            self.assertIn("steps", env)
            self.assertEqual(len(env["steps"]), 1)
            step = env["steps"][0]
            self.assertEqual(step["name"], "audit-step")
            self.assertTrue(step["passed"])
            self.assertEqual(step["peak_mem_estimate"], 4096)
            self.assertIn("version", env)
            self.assertEqual(env["runbook_path"], path)
        finally:
            os.unlink(path)

    def test_runbook_error_dies_two(self):
        path = "/nonexistent/runbook.json"
        ns = mock.MagicMock()
        ns.runbook = path
        ns.json = False
        ns.only_violations = False
        with mock.patch.object(sys, "stderr", io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                rb.cmd_run(ns)
        self.assertEqual(cm.exception.code, 2)


class TestMainDispatch(unittest.TestCase):
    """Argparse routes correctly; exit code semantics."""

    def test_no_subcommand_exits_two(self):
        with self.assertRaises(SystemExit):
            rb.main([])

    def test_run_returns_zero_for_clean_run(self):
        path = tempfile.NamedTemporaryFile("w", delete=False, suffix=".json")
        json.dump([{"name": "x", "script": "pass",
                    "expect": {"exit_code": 0}}], path)
        path.close()
        try:
            queue = iter([self._envelope_ok().encode()])

            def fake_run(*a, **kw):
                cp = mock.Mock()
                cp.stdout = next(queue)
                cp.stderr = b""
                cp.returncode = 0
                return cp

            with (mock.patch.object(rb.subprocess, "run",
                                    side_effect=fake_run),
                  mock.patch.object(sys, "stdout", io.StringIO()),
                  mock.patch.object(sys, "stderr", io.StringIO())):
                rc = rb.main(["run", path.name])
            self.assertEqual(rc, 0)
        finally:
            os.unlink(path.name)

    @staticmethod
    def _envelope_ok(exit_code=0):
        return json.dumps({
            "exit_code": exit_code, "stdout": "", "stderr": "",
            "wall_clock_ms": 1, "timeout_hit": False,
            "peak_mem_estimate": 0})


if __name__ == "__main__":
    unittest.main()
