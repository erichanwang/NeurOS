#!/usr/bin/env python3
"""Tests for neuros-bench regression benchmark harness.

These tests do not need real container kernel delegation because
they mock subprocess.run and the inner _run_workload helper. They
assert:

  * argparse dispatch routes list / run / batch / compare correctly
  * --dry-run-equivalent paths emit metrics JSON shaped per the contract
  * compare-mode rejects regressions beyond --tolerance-wall-pct / mem
  * builtin workload registry contains the documented 8 entries
  * _pct_delta handles None + zero-base gracefully
  * _render_fn strips the leading `def _w_xxx():` line and re-indents
"""
import argparse
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
_BENCH_PATH = os.path.join(
    ROOT, "config", "includes.chroot", "usr", "local", "bin", "neuros-bench")


def _load_neuros_bench():
    """Load `neuros-bench` (no .py suffix in its install path) by
    compiling its source and exec-ing in a fresh module namespace.
    Same pattern as `_load_neuros_sandbox` in test_sandbox.py."""
    with open(_BENCH_PATH) as f:
        source = f.read()
    code = compile(source, _BENCH_PATH, "exec")
    module = sys.modules.get("neuros_bench") or types.ModuleType("neuros_bench")
    module.__file__ = _BENCH_PATH
    sys.modules["neuros_bench"] = module
    exec(code, module.__dict__)
    return module


nb = _load_neuros_bench()


class TestWorkloadRegistry(unittest.TestCase):
    """Locks the workload suite membership so an accidental rename or
    drop is a visible test failure rather than a silent regression."""

    EXPECTED = frozenset({
        "cpu_tight", "json_parse", "regex_compile", "subproc_spawn",
        "mem_grow", "file_io", "ctypes_call", "string_ops",
    })

    def test_expected_workloads_present(self):
        self.assertEqual(set(nb.WORKLOADS), self.EXPECTED)

    def test_each_workload_has_callable_and_baseline(self):
        for name, (fn, baseline) in nb.WORKLOADS.items():
            self.assertTrue(callable(fn),
                            f"workload {name} fn is not callable")
            self.assertIsInstance(baseline, int)
            self.assertGreater(baseline, 0,
                               f"workload {name} baseline_ms must be > 0")

    def test_registered_workloads_distinct(self):
        # Each fn is a top-level function with a distinct identity.
        seen = set()
        for name, (fn, _) in nb.WORKLOADS.items():
            self.assertNotIn(id(fn), seen,
                             f"workload {name} shares identity with "
                             "another workload")
            seen.add(id(fn))


class TestRenderFn(unittest.TestCase):
    """Locks the contract: _render_fn strips the def line and yields
    a re-indented body so the inner try/except sees uniform indent."""

    def test_renders_function_body_without_def_line(self):
        rendered = nb._render_fn(nb._w_cpu_tight)
        text = "\n".join(rendered)
        self.assertNotIn("def _w_cpu_tight", text)
        self.assertIn("def fib", text)  # nested function preserved
        self.assertIn("fib(28)", text)  # the trailing call preserved

    def test_each_builtin_renders(self):
        for name, (fn, _) in nb.WORKLOADS.items():
            rendered = nb._render_fn(fn)
            self.assertTrue(rendered,
                            f"workload {name} rendered to empty list")


class TestPctDelta(unittest.TestCase):
    """Locks the percent-delta helpers' edge cases."""

    def test_zero_base_returns_none(self):
        self.assertIsNone(nb._pct_delta(0, 100))

    def test_negative_delta(self):
        # Improvement: candidate is faster than baseline.
        self.assertAlmostEqual(nb._pct_delta(100, 80), -20.0)

    def test_positive_delta(self):
        # Regression: candidate is slower.
        self.assertAlmostEqual(nb._pct_delta(100, 130), 30.0)

    def test_optional_handles_none(self):
        self.assertIsNone(nb._pct_delta_optional(None, 100))
        self.assertIsNone(nb._pct_delta_optional(100, None))

    def test_optional_handles_zero_base(self):
        self.assertIsNone(nb._pct_delta_optional(0, 100))


class TestCompareFunction(unittest.TestCase):
    """The compare subcommand is the load-bearing piece for CI: exit
    1 if any workload's wall or mem regresses beyond tolerance."""

    def _metrics(self, runs):
        return {
            "runs": runs,
            "total_wall_clock_ms": 12345,
            "config": {},
            "neuros_bench_version": nb.NEUROS_BENCH_VERSION,
        }

    def _run_row(self, name, wall_ms, peak=None):
        return {
            "name": name, "wall_clock_ms": wall_ms,
            "exit_code": 0, "stdout": "", "stderr": "",
            "timeout_hit": False, "peak_mem_estimate": peak,
        }

    def _write_metrics(self, runs):
        f = tempfile.NamedTemporaryFile("w", delete=False, suffix=".json")
        json.dump(self._metrics(runs), f)
        f.close()
        return f.name

    def test_no_regression_exits_zero(self):
        a = self._write_metrics([
            self._run_row("cpu_tight", 1000, peak=10_000_000)
        ])
        b = self._write_metrics([
            self._run_row("cpu_tight", 1050, peak=10_500_000)
        ])
        ns = mock.MagicMock()
        ns.baseline = a
        ns.candidate = b
        ns.tolerance_wall_pct = 15.0
        ns.tolerance_mem_pct = 25.0
        # Capture both stdout and stderr; compare-mode writes the
        # table on stdout and the verdict on stderr.
        buf_out, buf_err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "stdout", buf_out), \
             mock.patch.object(sys, "stderr", buf_err):
            rc = nb.cmd_compare(ns)
        self.assertEqual(rc, 0, buf_out.getvalue())
        self.assertIn("OK", buf_out.getvalue())
        self.assertNotIn("REGRESSION", buf_out.getvalue())
        os.unlink(a)
        os.unlink(b)

    def test_wall_regression_exits_one(self):
        a = self._write_metrics([
            self._run_row("cpu_tight", 1000, peak=10_000_000)
        ])
        b = self._write_metrics([
            self._run_row("cpu_tight", 1300, peak=10_500_000)
        ])
        ns = mock.MagicMock()
        ns.baseline = a
        ns.candidate = b
        ns.tolerance_wall_pct = 15.0
        ns.tolerance_mem_pct = 25.0
        buf_out, buf_err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "stdout", buf_out), \
             mock.patch.object(sys, "stderr", buf_err):
            rc = nb.cmd_compare(ns)
        self.assertEqual(rc, 1)
        self.assertIn("REGRESSION", buf_out.getvalue())
        os.unlink(a)
        os.unlink(b)

    def test_new_workload_added_in_candidate_is_not_regression(self):
        """A NEW workload appears only in candidate, not in baseline.
        This is an addition, NOT a regression — CI should pass with
        exit 0 and the row should be marked NEW (informational)."""
        a = self._write_metrics([
            self._run_row("cpu_tight", 1000, peak=10_000_000)
        ])
        b = self._write_metrics([
            self._run_row("cpu_tight", 1000, peak=10_000_000),
            self._run_row("json_parse", 800, peak=10_000_000),
        ])
        ns = mock.MagicMock()
        ns.baseline = a
        ns.candidate = b
        ns.tolerance_wall_pct = 15.0
        ns.tolerance_mem_pct = 25.0
        buf_out, buf_err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "stdout", buf_out), \
             mock.patch.object(sys, "stderr", buf_err):
            rc = nb.cmd_compare(ns)
        self.assertEqual(rc, 0, buf_out.getvalue())
        self.assertIn("NEW", buf_out.getvalue())
        os.unlink(a)
        os.unlink(b)

    def test_dropped_workload_in_candidate_is_regression(self):
        """A workload present in baseline but absent in candidate is a
        DROPPED workload — CI should exit 1."""
        a = self._write_metrics([
            self._run_row("cpu_tight", 1000, peak=10_000_000),
            self._run_row("string_ops", 500, peak=10_000_000),
        ])
        b = self._write_metrics([
            self._run_row("cpu_tight", 1000, peak=10_000_000),
        ])
        ns = mock.MagicMock()
        ns.baseline = a
        ns.candidate = b
        ns.tolerance_wall_pct = 15.0
        ns.tolerance_mem_pct = 25.0
        buf_out, buf_err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "stdout", buf_out), \
             mock.patch.object(sys, "stderr", buf_err):
            rc = nb.cmd_compare(ns)
        self.assertEqual(rc, 1)
        self.assertIn("DROPPED", buf_out.getvalue())
        os.unlink(a)
        os.unlink(b)

    def test_mem_regression_exits_one(self):
        a = self._write_metrics([
            self._run_row("mem_grow", 300, peak=10_000_000)
        ])
        b = self._write_metrics([
            self._run_row("mem_grow", 305, peak=15_000_000)
        ])
        ns = mock.MagicMock()
        ns.baseline = a
        ns.candidate = b
        ns.tolerance_wall_pct = 15.0
        ns.tolerance_mem_pct = 25.0
        buf_out, buf_err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "stdout", buf_out), \
             mock.patch.object(sys, "stderr", buf_err):
            rc = nb.cmd_compare(ns)
        self.assertEqual(rc, 1)
        self.assertIn("REGRESSION", buf_out.getvalue())
        os.unlink(a)
        os.unlink(b)


class TestRunWorkloadMocked(unittest.TestCase):
    """Drive _run_workload with a mocked subprocess.run so we exercise
    the JSON-envelope-parsing path without invoking the real
    neuros-sandbox binary."""

    def _fake_completed(self, stdout_text, returncode=0, stderr=b""):
        cp = mock.Mock(returncode=returncode, stdout=stdout_text.encode())
        cp.stderr = stderr
        return cp

    def test_parses_top_line_envelope(self):
        env = {"exit_code": 0, "wall_clock_ms": 250, "timeout_hit": False,
               "peak_mem_estimate": 31457280}
        cp = self._fake_completed(json.dumps(env))
        with mock.patch.object(nb.subprocess, "run", return_value=cp), \
             mock.patch.object(nb, "_load_script",
                               create=True, return_value=b"x"):
            out = nb._run_workload("cpu_tight", 60, "256M", 64)
        self.assertEqual(out["name"], "cpu_tight")
        self.assertEqual(out["wall_clock_ms"], 250)
        self.assertEqual(out["peak_mem_estimate"], 31457280)

    def test_no_envelope_returns_fallback_record(self):
        cp = self._fake_completed("")
        with mock.patch.object(nb.subprocess, "run", return_value=cp):
            out = nb._run_workload("cpu_tight", 60, "256M", 64)
        self.assertEqual(out["name"], "cpu_tight")
        self.assertEqual(out["wall_clock_ms"], 0)
        self.assertIsNone(out["peak_mem_estimate"])


class TestMainDispatch(unittest.TestCase):
    """Argparse routes subcommands correctly."""

    def test_unknown_subcommand_exits(self):
        with self.assertRaises(SystemExit):
            nb.main(["nope"])

    def test_list_dispatches(self):
        # argparse print_help writes "usage: ..." on stdout before our
        # cmd_list handler runs when an unknown option trips argparse;
        # for the `list` subcommand alone, main should return 0.
        with mock.patch.object(sys, "stdout", io.StringIO()), \
             mock.patch.object(sys, "stderr", io.StringIO()):
            rc = nb.main(["list"])
        self.assertEqual(rc, 0)

    def test_list_emits_cpu_tight_workload(self):
        buf = io.StringIO()
        with mock.patch.object(sys, "stdout", buf), \
             mock.patch.object(sys, "stderr", io.StringIO()):
            nb.main(["list"])
        out = buf.getvalue()
        self.assertIn("available workloads", out)
        self.assertIn("cpu_tight", out)

    def test_run_unknown_workload_dies(self):
        with mock.patch.object(sys, "stderr", io.StringIO()), \
             self.assertRaises(SystemExit) as cm:
            nb.main(["run", "does-not-exist"])
        self.assertEqual(cm.exception.code, 2)


class TestConfigBlock(unittest.TestCase):
    """Locks the schema of the metrics.json 'config' sub-record."""

    def test_keys_present(self):
        ns = mock.MagicMock()
        ns.timeout = 60
        ns.mem = "256M"
        ns.pids = 64
        cfg = nb._config_block(ns)
        self.assertEqual(cfg["per_workload_timeout_seconds"], 60)
        self.assertEqual(cfg["mem_cap"], "256M")
        self.assertEqual(cfg["pids_cap"], 64)


if __name__ == "__main__":
    unittest.main()
