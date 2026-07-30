"""Tests for neuros-verify (consume-anything verifier).

Runs purely against the production script via compile()+exec() so we
do not need it on $PATH. No subprocess shell-out is exercised here
on purpose: every interesting invariant (kind detection, per-kind
verification, aggregate merge, --json shape) is reachable from
Python directly. Sandbox+policy integration is tested by writing a
small on-disk policy manifest in a tempdir and pointing verify at
it via --policy.
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

VERIFY_PATH = "config/includes.chroot/usr/local/bin/neuros-verify"
POLICY_PATH = "config/includes.chroot/usr/local/bin/neuros-policy"


def _load_module():
    with open(VERIFY_PATH, "r", encoding="utf-8") as f:
        src = f.read()
    if src.startswith("#!"):
        src = src.split("\n", 1)[1]
    code = compile(src, VERIFY_PATH, "exec")
    mod = types.ModuleType("neuros_verify_under_test")
    # Set __file__ BEFORE exec so the production module's
    # top-level references to __file__ resolve correctly
    # (e.g. the policy script resolver's candidate list).
    mod.__file__ = VERIFY_PATH
    exec(code, mod.__dict__)
    return mod


def _write_json(obj):
    """Dump ``obj`` to a temp .json file and return its path string.
    """
    fd, p = tempfile.mkstemp(prefix="neuros-verify-", suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(obj, f)
    return p


def _good_policy():
    """A conformant policy manifest for sandbox+policy integration
    tests. Same shape as test_policy._good_policy.
    """
    return {
        "name": "neuros-default",
        "version": "1.0.0",
        "defaults": {
            "mem": "256M",
            "pids": 64,
            "cpu_quota": 50000,
            "timeout": 30,
        },
        "profiles": {
            "strict":     ["CAP_NET_RAW", "CAP_SYS_ADMIN"],
            "moderate":   ["CAP_NET_RAW"],
            "permissive": [],
        },
        "net": "private",
        "readonly": True,
        "env_allowlist": ["PATH"],
        "syscalls": None,
    }


def _write_policy():
    return _write_json(_good_policy())


def _ok_envelope(**overrides):
    base = {
        "exit_code": 0, "stdout": "", "stderr": "",
        "wall_clock_ms": 1000, "timeout_hit": False,
        "peak_mem_estimate": 64 * 1024 * 1024,
    }
    base.update(overrides)
    return base


def _bench_metrics(runs=None):
    return {
        "runs": runs if runs is not None else [
            {
                "name": "cpu_tight", "wall_clock_ms": 1100,
                "exit_code": 0, "stdout": "", "stderr": "",
                "timeout_hit": False,
                "peak_mem_estimate": 32 * 1024 * 1024,
            },
            {
                "name": "json_parse", "wall_clock_ms": 900,
                "exit_code": 0, "stdout": "", "stderr": "",
                "timeout_hit": False,
                "peak_mem_estimate": 18 * 1024 * 1024,
            },
        ],
        "total_wall_clock_ms": 2000,
        "config": {},
        "neuros_bench_version": "0.1",
    }


class TestCompile(unittest.TestCase):
    def test_compiles_clean(self):
        self.assertTrue(compileall.compile_file(VERIFY_PATH,
                                                 quiet=1,
                                                 force=True))


class TestDetectKind(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vf = _load_module()

    def test_bench_by_version_key(self):
        self.assertEqual(self.vf._detect_kind(_bench_metrics()),
                         "bench")

    def test_policy_by_version_key(self):
        env = {"ok": True, "errors": [], "name": "x",
                "version": "1.0.0", "neuros_policy_version": "0.1"}
        self.assertEqual(self.vf._detect_kind(env), "policy")

    def test_replay_by_version_key(self):
        env = {"ok": True, "neuros_replay_version": "0.1",
                "rule_violations": []}
        self.assertEqual(self.vf._detect_kind(env), "replay")

    def test_runbook_by_structure(self):
        env = {"runbook_path": "/tmp/rb.json",
                "steps": [{"name": "x", "ok": True}]}
        self.assertEqual(self.vf._detect_kind(env), "runbook")

    def test_sandbox_by_structure(self):
        self.assertEqual(self.vf._detect_kind(_ok_envelope()),
                         "sandbox")

    def test_runbook_priority_over_sandbox(self):
        # If both structural patterns match, runbook wins because
        # it's checked first (has the more specific runbook_path).
        env = {"runbook_path": "/x", "steps": [],
                "exit_code": 0, "wall_clock_ms": 0,
                "timeout_hit": False}
        self.assertEqual(self.vf._detect_kind(env), "runbook")

    def test_unknown(self):
        self.assertEqual(self.vf._detect_kind({"foo": "bar"}),
                         "unknown")


class TestLoadEnvelope(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vf = _load_module()

    def test_missing_file(self):
        with self.assertRaises(self.vf.VerifyError) as cm:
            self.vf._load_envelope("/nonexistent/env.json")
        self.assertIn("cannot read", str(cm.exception))

    def test_malformed_json(self):
        fd, p = tempfile.mkstemp(prefix="nv-bad-", suffix=".json")
        try:
            with os.fdopen(fd, "w") as f:
                f.write("not json {{{")
            with self.assertRaises(self.vf.VerifyError) as cm:
                self.vf._load_envelope(p)
            self.assertIn("not valid JSON", str(cm.exception))
        finally:
            os.unlink(p)

    def test_root_must_be_object(self):
        path = _write_json([1, 2, 3])
        try:
            with self.assertRaises(self.vf.VerifyError):
                self.vf._load_envelope(path)
        finally:
            os.unlink(path)


class TestPctDelta(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vf = _load_module()

    def test_normal(self):
        self.assertEqual(self.vf._pct_delta(1000, 1100), 10.0)
        self.assertEqual(self.vf._pct_delta(1000, 900), -10.0)

    def test_zero_div(self):
        self.assertIsNone(self.vf._pct_delta(0, 100))

    def test_missing(self):
        self.assertIsNone(self.vf._pct_delta(None, 100))
        self.assertIsNone(self.vf._pct_delta(100, None))


class TestVerifyPolicyVerdict(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vf = _load_module()

    def test_ok_true(self):
        ok, viols = self.vf._verify_policy_verdict(
            {"ok": True, "errors": []})
        self.assertTrue(ok)
        self.assertEqual(viols, [])

    def test_ok_false_with_errors(self):
        ok, viols = self.vf._verify_policy_verdict(
            {"ok": False, "errors": ["bad mem"]})
        self.assertFalse(ok)
        self.assertIn("bad mem", viols)

    def test_ok_false_without_errors(self):
        ok, viols = self.vf._verify_policy_verdict({"ok": False})
        self.assertFalse(ok)
        self.assertEqual(len(viols), 1)

    def test_ok_other_type(self):
        ok, viols = self.vf._verify_policy_verdict({"ok": "yes"})
        self.assertFalse(ok)


class TestVerifyReplayVerdict(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vf = _load_module()

    def test_ok_true(self):
        ok, viols = self.vf._verify_replay_verdict(
            {"ok": True, "rule_violations": []})
        self.assertTrue(ok)

    def test_ok_false_with_rule_violations(self):
        ok, viols = self.vf._verify_replay_verdict({
            "ok": False,
            "rule_violations": ["wall_clock_pct_delta 50%"]})
        self.assertFalse(ok)
        self.assertEqual(viols,
                         ["wall_clock_pct_delta 50%"])


class TestVerifyBench(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vf = _load_module()

    def test_no_runs(self):
        ok, _ = self.vf._verify_bench({"runs": []}, None)
        self.assertTrue(ok)

    def test_runs_not_a_list(self):
        ok, viols = self.vf._verify_bench({"runs": "nope"}, None)
        self.assertFalse(ok)

    def test_runs_with_one_nonzero_exit(self):
        ok, viols = self.vf._verify_bench(
            _bench_metrics([{"name": "x", "exit_code": 1,
                              "wall_clock_ms": 0}]),
            None)
        self.assertFalse(ok)
        self.assertTrue(any("exit_code=1" in v for v in viols))

    def test_with_baseline_missing_file(self):
        ok, viols = self.vf._verify_bench(
            _bench_metrics(), "/nonexistent/baseline.json")
        self.assertFalse(ok)

    def test_with_baseline_wall_clock_regression(self):
        base = _bench_metrics()
        cand = _bench_metrics()
        cand["runs"][0]["wall_clock_ms"] = 5000  # +354%
        b = _write_json(base)
        try:
            ok, viols = self.vf._verify_bench(cand, b)
            self.assertFalse(ok)
            self.assertTrue(any("wall_clock_pct_delta" in v
                                for v in viols))
        finally:
            os.unlink(b)

    def test_with_baseline_conformant(self):
        b = _write_json(_bench_metrics())
        try:
            ok, viols = self.vf._verify_bench(_bench_metrics(), b)
            self.assertTrue(ok)
            self.assertEqual(viols, [])
        finally:
            os.unlink(b)

    def test_with_baseline_new_run_in_candidate_not_violation(self):
        base = _bench_metrics(runs=[{
            "name": "cpu_tight", "wall_clock_ms": 1100,
            "exit_code": 0, "timeout_hit": False,
            "peak_mem_estimate": 32 * 1024 * 1024}])
        cand = _bench_metrics()
        # Candidate has an extra run (json_parse) not in baseline.
        b = _write_json(base)
        try:
            ok, viols = self.vf._verify_bench(cand, b)
            # The existing cpu_tight run is conformant and the new
            # json_parse run is not a regression (no baseline entry).
            self.assertTrue(ok)
        finally:
            os.unlink(b)


class TestVerifyRunbook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vf = _load_module()

    def test_conformant(self):
        env = {"runbook_path": "/tmp/rb.json",
                "steps": [{"name": "a", "ok": True},
                          {"name": "b", "ok": True}]}
        ok, viols = self.vf._verify_runbook(env)
        self.assertTrue(ok)

    def test_missing_path(self):
        ok, viols = self.vf._verify_runbook({"steps": []})
        self.assertFalse(ok)

    def test_step_not_object(self):
        env = {"runbook_path": "/x",
                "steps": ["stringy", {"name": "y", "ok": True}]}
        ok, viols = self.vf._verify_runbook(env)
        self.assertFalse(ok)
        self.assertTrue(any("not an object" in v for v in viols))

    def test_step_missing_name(self):
        env = {"runbook_path": "/x",
                "steps": [{"ok": True}]}
        ok, viols = self.vf._verify_runbook(env)
        self.assertFalse(ok)


class TestVerifySandbox(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vf = _load_module()

    def test_conformant_envelope(self):
        # Load the policy MODULE (Python source) and pass a
        # separate MANIFEST path to _verify_sandbox. The SCRIPT
        # is reusable across manifests; the manifest is per-run.
        with open(POLICY_PATH, "r") as f:
            psrc = f.read()
        if psrc.startswith("#!"):
            psrc = psrc.split("\n", 1)[1]
        pcode = compile(psrc, POLICY_PATH, "exec")
        pmod = types.ModuleType("policy_loader")
        pmod.__file__ = POLICY_PATH
        exec(pcode, pmod.__dict__)

        manifest_path = _write_policy()
        try:
            ok, viols = self.vf._verify_sandbox(
                _ok_envelope(), pmod, manifest_path)
            self.assertTrue(ok)
        finally:
            os.unlink(manifest_path)

    def test_violation_envelope(self):
        with open(POLICY_PATH, "r") as f:
            psrc = f.read()
        if psrc.startswith("#!"):
            psrc = psrc.split("\n", 1)[1]
        pcode = compile(psrc, POLICY_PATH, "exec")
        pmod = types.ModuleType("policy_loader")
        pmod.__file__ = POLICY_PATH
        exec(pcode, pmod.__dict__)

        manifest_path = _write_policy()
        try:
            # timeout_hit=True is always a violation.
            ok, viols = self.vf._verify_sandbox(
                _ok_envelope(timeout_hit=True),
                pmod, manifest_path)
            self.assertFalse(ok)
            self.assertTrue(any("timeout_hit" in v
                                for v in viols))
        finally:
            os.unlink(manifest_path)


class TestVerifyUnknown(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vf = _load_module()

    def test_unrecognized_envelope(self):
        ok, viols = self.vf._verify_unknown({"foo": "bar"})
        self.assertFalse(ok)
        self.assertTrue(any("unrecognized" in v for v in viols))


class TestMainDispatch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vf = _load_module()

    def test_text_line_shape(self):
        path = _write_json({"ok": True, "errors": [],
                            "neuros_policy_version": "0.1"})
        try:
            buf = io.StringIO()
            with mock.patch.object(sys, "stdout", buf):
                rc = self.vf.main([path])
            self.assertEqual(rc, 0)
            out = buf.getvalue()
            self.assertIn("verdict=PASS", out)
            self.assertIn("source=policy", out)
            self.assertIn("violations=0", out)
            self.assertIn("source=aggregate", out)
        finally:
            os.unlink(path)

    def test_text_line_for_sandbox_without_policy_fails(self):
        path = _write_json(_ok_envelope())
        try:
            buf = io.StringIO()
            with mock.patch.object(sys, "stdout", buf), \
                 mock.patch.object(sys, "stderr", buf):
                rc = self.vf.main([path])
            self.assertEqual(rc, 1)
            self.assertIn("verdict=FAIL", buf.getvalue())
            self.assertIn("source=sandbox", buf.getvalue())
            self.assertIn("violations=1", buf.getvalue())
        finally:
            os.unlink(path)

    def test_text_line_for_sandbox_with_policy_passes(self):
        path = _write_json(_ok_envelope())
        policy_path = _write_policy()
        try:
            buf = io.StringIO()
            with mock.patch.object(sys, "stdout", buf):
                rc = self.vf.main([path, "--policy", policy_path])
            self.assertEqual(rc, 0)
            self.assertIn("verdict=PASS", buf.getvalue())
            self.assertIn("source=sandbox", buf.getvalue())
        finally:
            os.unlink(path)
            os.unlink(policy_path)

    def test_unknown_envelope_verdict_fail(self):
        path = _write_json({"foo": 1})
        try:
            buf = io.StringIO()
            with mock.patch.object(sys, "stdout", buf), \
                 mock.patch.object(sys, "stderr", buf):
                rc = self.vf.main([path])
            self.assertEqual(rc, 1)
            self.assertIn("verdict=FAIL", buf.getvalue())
            self.assertIn("source=unknown", buf.getvalue())
        finally:
            os.unlink(path)

    def test_json_envelope_shape(self):
        path = _write_json({"ok": True, "errors": [],
                            "neuros_policy_version": "0.1"})
        try:
            buf = io.StringIO()
            with mock.patch.object(sys, "stdout", buf):
                rc = self.vf.main([path, "--json"])
            self.assertEqual(rc, 0)
            obj = json.loads(buf.getvalue().strip())
            self.assertTrue(obj["ok"])
            self.assertEqual(obj["aggregate"]["passes"], 1)
            self.assertEqual(obj["aggregate"]["failures"], 0)
            self.assertEqual(len(obj["parts"]), 1)
            self.assertEqual(obj["parts"][0]["source_kind"], "policy")
            self.assertIn("neuros_verify_version", obj)
        finally:
            os.unlink(path)

    def test_quiet_suppresses_per_file_lines(self):
        path = _write_json({"ok": True, "errors": [],
                            "neuros_policy_version": "0.1"})
        try:
            buf = io.StringIO()
            with mock.patch.object(sys, "stdout", buf):
                rc = self.vf.main([path, "--quiet"])
            self.assertEqual(rc, 0)
            out = buf.getvalue()
            # No per-file 'source=policy' line.
            self.assertNotIn("source=policy", out)
            self.assertIn("source=aggregate", out)
        finally:
            os.unlink(path)

    def test_multi_file_and_merge(self):
        good = _write_json({"ok": True, "errors": [],
                            "neuros_policy_version": "0.1"})
        bad = _write_json({"ok": False, "errors": ["x"],
                            "neuros_policy_version": "0.1"})
        try:
            buf = io.StringIO()
            with mock.patch.object(sys, "stdout", buf), \
                 mock.patch.object(sys, "stderr", buf):
                rc = self.vf.main([good, bad])
            # One file passes, one fails → overall FAIL.
            self.assertEqual(rc, 1)
            out = buf.getvalue()
            self.assertIn("passes=1", out)
            self.assertIn("failures=1", out)
            # The aggregate (last) line must report the overall FAIL
            # verdict, not just one of the per-file lines.
            last_line = out.strip().splitlines()[-1]
            self.assertTrue(last_line.startswith("verdict=FAIL "))
            self.assertIn("source=aggregate", last_line)
        finally:
            os.unlink(good); os.unlink(bad)

    def test_missing_file_returns_two(self):
        buf = io.StringIO()
        with mock.patch.object(sys, "stdout", buf), \
             mock.patch.object(sys, "stderr", io.StringIO()):
            with self.assertRaises(SystemExit):
                self.vf.main(["/nonexistent/env.json"])

    def test_bench_with_baseline(self):
        base = _bench_metrics()
        cand = _bench_metrics()
        cand_path = _write_json(cand)
        base_path = _write_json(base)
        try:
            buf = io.StringIO()
            with mock.patch.object(sys, "stdout", buf):
                rc = self.vf.main([cand_path,
                                    "--bench-baseline", base_path])
            self.assertEqual(rc, 0)
            self.assertIn("source=bench", buf.getvalue())
            self.assertIn("violations=0", buf.getvalue())
        finally:
            os.unlink(cand_path); os.unlink(base_path)


class TestResolvePolicyScript(unittest.TestCase):
    """Defensive: the resolver raises VerifyError with a clear
    message when NO candidate path exists. In a dev checkout the
    sibling-of-neuros-verify candidate is a real file, so the env
    override alone isn't enough to force a miss -- os.path.isfile
    is patched to make every candidate look absent.
    """

    @classmethod
    def setUpClass(cls):
        cls.vf = _load_module()

    @classmethod
    def tearDownClass(cls):
        # Clear the module-level cache so subsequent test classes
        # re-resolve with the live env (the cache is shared
        # singleton state that we don't want to leak across
        # test classes).
        cls.vf._CACHED_POLICY_SCRIPT_MOD = None
        cls.vf._CACHED_POLICY_SCRIPT_PATH = None

    def test_missing_script_raises(self):
        with mock.patch.dict(os.environ,
                             {"NEUROS_POLICY_SCRIPT":
                              "/nonexistent/script"},
                             clear=False), \
             mock.patch("os.path.isfile", return_value=False):
            self.vf._CACHED_POLICY_SCRIPT_MOD = None
            self.vf._CACHED_POLICY_SCRIPT_PATH = None
            with self.assertRaises(self.vf.VerifyError) as cm:
                self.vf._resolve_policy_script()
            msg = str(cm.exception)
            self.assertIn("cannot locate", msg)
            self.assertIn("/nonexistent/script", msg)


if __name__ == "__main__":
    unittest.main()
