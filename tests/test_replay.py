"""Tests for neuros-replay (offline diagnostics over envelopes).

Runs purely against the production script via compile()+exec() so we
do not need it on $PATH. No subprocess shell-out is exercised here on
purpose: every interesting invariant (bounds of pct_delta, missing
fields, tolerance overrides, JSON envelope shape) is reachable from
Python directly. The `extract` subcommand writes to stdout which we
capture via sys.stdout mocks.
"""
import compileall
import io
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

REPLAY_PATH = "config/includes.chroot/usr/local/bin/neuros-replay"


def _load_module():
    with open(REPLAY_PATH, "r", encoding="utf-8") as f:
        src = f.read()
    if src.startswith("#!"):
        src = src.split("\n", 1)[1]
    code = compile(src, REPLAY_PATH, "exec")
    mod = types.ModuleType("neuros_replay_under_test")
    exec(code, mod.__dict__)
    return mod


def _envelope(**overrides):
    """A conformant sandbox envelope with all fields present.
    Picked exit_code=0, wall_clock_ms=1000, peak_mem=64M so the
    tests can mutate one field at a time without making the envelope
    regress accidentally.
    """
    base = {
        "exit_code": 0,
        "stdout": "",
        "stderr": "",
        "wall_clock_ms": 1000,
        "timeout_hit": False,
        "peak_mem_estimate": 64 * 1024 * 1024,
    }
    base.update(overrides)
    return base


def _write_envelope(env):
    """Dump ``env`` to a temp .json file and return its path string."""
    fd, p = tempfile.mkstemp(prefix="neuros-replay-", suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(env, f)
    return p


class TestCompile(unittest.TestCase):
    def test_compiles_clean(self):
        self.assertTrue(compileall.compile_file(REPLAY_PATH,
                                                 quiet=1,
                                                 force=True))


class TestPctDelta(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rp = _load_module()

    def test_normal_positive_delta(self):
        # b = 1100, a = 1000 → +10%
        self.assertEqual(self.rp._pct_delta(1000, 1100), 10.0)

    def test_normal_negative_delta(self):
        self.assertEqual(self.rp._pct_delta(1000, 900), -10.0)

    def test_zero_returns_none(self):
        # Zero in the denominator would explode to +inf; surface as None.
        self.assertIsNone(self.rp._pct_delta(0, 100))

    def test_missing_returns_none(self):
        self.assertIsNone(self.rp._pct_delta(None, 100))
        self.assertIsNone(self.rp._pct_delta(100, None))
        self.assertIsNone(self.rp._pct_delta(None, None))

    def test_non_numeric_returns_none(self):
        self.assertIsNone(self.rp._pct_delta("foo", 100))
        self.assertIsNone(self.rp._pct_delta(100, "bar"))

    def test_rounded_to_two_decimals(self):
        # (103 - 100) / 100 * 100 = 3.0
        self.assertEqual(self.rp._pct_delta(100, 103), 3.0)


class TestFormatBytes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rp = _load_module()

    def test_none_returns_na(self):
        self.assertEqual(self.rp._format_bytes(None), "n/a")

    def test_bytes(self):
        self.assertEqual(self.rp._format_bytes(512), "512B")

    def test_kib(self):
        self.assertEqual(self.rp._format_bytes(2048), "2.0KiB")

    def test_mib(self):
        self.assertEqual(self.rp._format_bytes(64 * 1024 * 1024),
                         "64.0MiB")


class TestDiff(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rp = _load_module()

    def test_identical_envelopes_pass(self):
        env = _envelope()
        verdict = self.rp.diff_envelopes(env, env, 10.0, 20.0)
        self.assertTrue(verdict["ok"])
        self.assertEqual(verdict["rule_violations"], [])
        self.assertEqual(verdict["wall_clock_pct_delta"], 0.0)

    def test_wall_clock_within_tolerance_passes(self):
        # +5% is within default 10% wall-clock tolerance.
        verdict = self.rp.diff_envelopes(
            _envelope(wall_clock_ms=1000),
            _envelope(wall_clock_ms=1050),
            10.0, 20.0)
        self.assertTrue(verdict["ok"])

    def test_wall_clock_over_tolerance_fails(self):
        # +50% is well outside default 10%.
        verdict = self.rp.diff_envelopes(
            _envelope(wall_clock_ms=1000),
            _envelope(wall_clock_ms=1500),
            10.0, 20.0)
        self.assertFalse(verdict["ok"])
        self.assertTrue(any("wall_clock_pct_delta" in v
                            for v in verdict["rule_violations"]))

    def test_peak_mem_over_tolerance_fails(self):
        # +50% memory.
        verdict = self.rp.diff_envelopes(
            _envelope(peak_mem_estimate=64 * 1024 * 1024),
            _envelope(peak_mem_estimate=96 * 1024 * 1024),
            10.0, 20.0)
        self.assertFalse(verdict["ok"])
        self.assertTrue(any("peak_mem_pct_delta" in v
                            for v in verdict["rule_violations"]))

    def test_peak_mem_null_skips_check(self):
        verdict = self.rp.diff_envelopes(
            _envelope(peak_mem_estimate=None),
            _envelope(peak_mem_estimate=None),
            10.0, 20.0)
        self.assertTrue(verdict["ok"])
        self.assertIsNone(verdict["peak_mem_pct_delta"])

    def test_exit_code_mismatch_fails(self):
        verdict = self.rp.diff_envelopes(
            _envelope(exit_code=0),
            _envelope(exit_code=1),
            10.0, 20.0)
        self.assertFalse(verdict["ok"])
        self.assertTrue(any("exit_code" in v
                            for v in verdict["rule_violations"]))

    def test_timeout_hit_mismatch_fails(self):
        verdict = self.rp.diff_envelopes(
            _envelope(timeout_hit=False),
            _envelope(timeout_hit=True),
            10.0, 20.0)
        self.assertFalse(verdict["ok"])
        self.assertTrue(any("timeout_hit" in v
                            for v in verdict["rule_violations"]))

    def test_zero_wall_clock_handled(self):
        # a has wall_clock_ms=0 → pct_delta is None → no violation
        verdict = self.rp.diff_envelopes(
            _envelope(wall_clock_ms=0),
            _envelope(wall_clock_ms=500),
            10.0, 20.0)
        self.assertTrue(verdict["ok"])
        self.assertIsNone(verdict["wall_clock_pct_delta"])

    def test_tight_tolerance_overrides_default(self):
        # Tolerances set to 1% — even +5% regresses.
        verdict = self.rp.diff_envelopes(
            _envelope(wall_clock_ms=1000),
            _envelope(wall_clock_ms=1050),
            1.0, 1.0)
        self.assertFalse(verdict["ok"])


class TestExplain(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rp = _load_module()

    def test_explain_envelope_includes_all_keys(self):
        info = self.rp.explain_envelope(_envelope())
        for k in ("exit_code", "wall_clock_ms", "peak_mem_estimate",
                   "timeout_hit", "stdout_bytes", "stderr_bytes"):
            self.assertIn(k, info)

    def test_explain_line_is_single_space_separated(self):
        info = self.rp.explain_envelope(_envelope())
        line = self.rp._explain_line(info)
        # Starts with the canonical key=value structure
        self.assertTrue(line.startswith("exit="))
        self.assertIn("wall=", line)
        self.assertIn("peak=64.0MiB", line)
        self.assertIn("timeout=False", line)

    def test_missing_fields_render_na(self):
        env = {"exit_code": 0}  # no wall / peak / etc.
        info = self.rp.explain_envelope(env)
        self.assertEqual(info["wall_clock_ms"], "n/a")
        self.assertEqual(info["peak_mem_estimate"], "n/a")
        line = self.rp._explain_line(info)
        self.assertIn("wall=n/a", line)
        self.assertIn("peak=n/a", line)


class TestLoadEnvelope(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rp = _load_module()

    def test_missing_file(self):
        with self.assertRaises(self.rp.ReplayError) as cm:
            self.rp._load_envelope("/nonexistent/envelope.json")
        self.assertIn("cannot read", str(cm.exception))

    def test_malformed_json(self):
        path = _write_envelope_str("not valid json {{{")
        try:
            with self.assertRaises(self.rp.ReplayError):
                self.rp._load_envelope(path)
        finally:
            os.unlink(path)

    def test_root_must_be_object(self):
        path = _write_envelope_str("[1, 2, 3]")
        try:
            with self.assertRaises(self.rp.ReplayError):
                self.rp._load_envelope(path)
        finally:
            os.unlink(path)


def _write_envelope_str(text):
    fd, p = tempfile.mkstemp(prefix="neuros-replay-bad-", suffix=".json")
    with os.fdopen(fd, "w") as f:
        f.write(text)
    return p


class TestMainDispatch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rp = _load_module()

    def _ok(self):
        return _envelope()

    def test_diff_returns_zero_for_identical(self):
        a = b = _write_envelope(self._ok())
        try:
            with mock.patch.object(sys, "stdout", io.StringIO()):
                rc = self.rp.main(["diff", a, b])
            self.assertEqual(rc, 0)
        finally:
            os.unlink(a)

    def test_diff_returns_one_for_regression(self):
        a = _write_envelope(self._ok())
        b = _write_envelope(self._ok() | {"wall_clock_ms": 9999})
        try:
            buf = io.StringIO()
            with mock.patch.object(sys, "stdout", buf), \
                 mock.patch.object(sys, "stderr", buf):
                rc = self.rp.main(["diff", a, b])
            self.assertEqual(rc, 1)
            self.assertIn("violation", buf.getvalue())
        finally:
            os.unlink(a); os.unlink(b)

    def test_diff_json_envelope_shape(self):
        # +5% on wall-clock is within the default 10% tolerance.
        a = _write_envelope(self._ok())
        b = _write_envelope(self._ok() | {"wall_clock_ms": 1050})
        try:
            buf = io.StringIO()
            with mock.patch.object(sys, "stdout", buf), \
                 mock.patch.object(sys, "stderr", io.StringIO()):
                rc = self.rp.main(["diff", "--json", a, b])
            self.assertEqual(rc, 0)
            obj = json.loads(buf.getvalue().strip())
            self.assertTrue(obj["ok"])
            self.assertEqual(obj["wall_clock_pct_delta"], 5.0)
            self.assertEqual(obj["peak_mem_pct_delta"], 0.0)
        finally:
            os.unlink(a); os.unlink(b)

    def test_diff_bad_input_returns_two(self):
        with mock.patch.object(sys, "stdout", io.StringIO()), \
             mock.patch.object(sys, "stderr", io.StringIO()):
            rc = self.rp.main(["diff", "/nonexistent/a",
                                "/nonexistent/b"])
        self.assertEqual(rc, 2)

    def test_explain_prints_line(self):
        path = _write_envelope(self._ok())
        try:
            buf = io.StringIO()
            with mock.patch.object(sys, "stdout", buf):
                rc = self.rp.main(["explain", path])
            self.assertEqual(rc, 0)
            self.assertIn("exit=0", buf.getvalue())
            self.assertIn("wall=1000ms", buf.getvalue())
        finally:
            os.unlink(path)

    def test_explain_json_envelope_shape(self):
        path = _write_envelope(self._ok())
        try:
            buf = io.StringIO()
            with mock.patch.object(sys, "stdout", buf):
                rc = self.rp.main(["explain", "--json", path])
            self.assertEqual(rc, 0)
            obj = json.loads(buf.getvalue().strip())
            self.assertEqual(obj["exit_code"], 0)
            self.assertEqual(obj["wall_clock_ms"], 1000)
            self.assertIn("neuros_replay_version", obj)
        finally:
            os.unlink(path)

    def test_extract_stdout(self):
        env = self._ok() | {"stdout": "hello\n"}
        path = _write_envelope(env)
        try:
            buf = io.StringIO()
            with mock.patch.object(sys, "stdout", buf), \
                 mock.patch.object(sys, "stderr", io.StringIO()):
                rc = self.rp.main(["extract", path,
                                    "--stream", "stdout"])
            self.assertEqual(rc, 0)
            self.assertIn("hello", buf.getvalue())
            self.assertNotIn("===STDERR===", buf.getvalue())
        finally:
            os.unlink(path)

    def test_extract_stderr(self):
        env = self._ok() | {"stderr": "boom\n"}
        path = _write_envelope(env)
        try:
            buf = io.StringIO()
            with mock.patch.object(sys, "stdout", buf), \
                 mock.patch.object(sys, "stderr", io.StringIO()):
                rc = self.rp.main(["extract", path,
                                    "--stream", "stderr"])
            self.assertEqual(rc, 0)
            self.assertIn("boom", buf.getvalue())
        finally:
            os.unlink(path)

    def test_extract_both_has_separator(self):
        env = self._ok() | {"stdout": "x", "stderr": "y"}
        path = _write_envelope(env)
        try:
            buf = io.StringIO()
            with mock.patch.object(sys, "stdout", buf), \
                 mock.patch.object(sys, "stderr", io.StringIO()):
                rc = self.rp.main(["extract", path,
                                    "--stream", "both"])
            self.assertEqual(rc, 0)
            self.assertIn("x", buf.getvalue())
            self.assertIn("===STDERR===", buf.getvalue())
            self.assertIn("y", buf.getvalue())
        finally:
            os.unlink(path)

    def test_extract_both_when_stdout_empty(self):
        # When one stream is empty, --stream both still emits
        # the ===STDERR=== separator so a downstream parser
        # can split the streams without field-name re-mapping.
        env = self._ok() | {"stdout": "", "stderr": "boom\n"}
        path = _write_envelope(env)
        try:
            buf = io.StringIO()
            with mock.patch.object(sys, "stdout", buf), \
                 mock.patch.object(sys, "stderr", io.StringIO()):
                rc = self.rp.main(["extract", path,
                                    "--stream", "both"])
            self.assertEqual(rc, 0)
            self.assertIn("===STDERR===", buf.getvalue())
            self.assertIn("boom", buf.getvalue())
        finally:
            os.unlink(path)

    def test_extract_both_when_stderr_empty(self):
        # Symmetric case to test_extract_both_when_stdout_empty:
        # if stderr is empty, --stream both still emits the
        # ===STDERR=== separator before the (empty) stderr
        # payload, so a downstream parser can rely on the
        # boundary marker in either stream condition.
        env = self._ok() | {"stdout": "hello\n", "stderr": ""}
        path = _write_envelope(env)
        try:
            buf = io.StringIO()
            with mock.patch.object(sys, "stdout", buf), \
                 mock.patch.object(sys, "stderr", io.StringIO()):
                rc = self.rp.main(["extract", path,
                                    "--stream", "both"])
            self.assertEqual(rc, 0)
            self.assertIn("hello", buf.getvalue())
            self.assertIn("===STDERR===", buf.getvalue())
        finally:
            os.unlink(path)
    def test_extract_nonexistent_returns_two(self):
        with mock.patch.object(sys, "stdout", io.StringIO()), \
             mock.patch.object(sys, "stderr", io.StringIO()):
            rc = self.rp.main(["extract", "/nonexistent/env.json"])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
