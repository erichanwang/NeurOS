"""Tests for neuros-policy (loader pattern mirrors test_sandbox.py).

Runs purely against the production script via compile()+exec() so we
do not need it on $PATH. No subprocess enforcement is exercised here
on purpose: every interesting invariant (bounds, regex shape, profile
emission, envelope reconciliation) is reachable from Python directly.
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

POLICY_PATH = "config/includes.chroot/usr/local/bin/neuros-policy"


def _load_module():
    with open(POLICY_PATH, "r", encoding="utf-8") as f:
        src = f.read()
    # Strip the shebang line for exec(); everything else is plain
    # Python 3 and re-exports cleanly when given a real module
    # namespace (so `cls.pl.validate_policy` style attribute access
    # works; a plain dict would fail with AttributeError on lookup).
    if src.startswith("#!"):
        src = src.split("\n", 1)[1]
    code = compile(src, POLICY_PATH, "exec")
    mod = types.ModuleType("neuros_policy_under_test")
    exec(code, mod.__dict__)
    return mod


class TestCompile(unittest.TestCase):
    def test_compiles_clean(self):
        # The wrapper imports no third-party modules, so py_compile
        # is a sufficient static check before we even try exec().
        self.assertTrue(compileall.compile_file(POLICY_PATH,
                                                 quiet=1,
                                                 force=True))


def _write_policy(d):
    """Dump ``d`` to a temp .json file and return its path string
    (not the wrapper, so the production loader can open() it)."""
    fd, p = tempfile.mkstemp(prefix="neuros-policy-", suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(d, f)
    return p


def _good_policy(**overrides):
    base = {
        "name": "neuros-default",
        "version": "1.0.0",
        "defaults": {
            "mem": "256M",
            "pids": 64,
            "cpu_quota": 50000,
            "timeout": 30,
        },
        "profiles": {
            "strict":     ["CAP_NET_RAW", "CAP_SYS_ADMIN", "CAP_SYS_PTRACE"],
            "moderate":   ["CAP_NET_RAW", "CAP_SYS_ADMIN"],
            "permissive": [],
        },
        "net": "private",
        "readonly": True,
        "env_allowlist": ["PATH", "LANG"],
        "syscalls": None,
    }
    base.update(overrides)
    return base


class TestValidate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pl = _load_module()

    def test_clean_policy_passes(self):
        path = _write_policy(_good_policy())
        try:
            errs, cleaned = self.pl.validate_policy(_good_policy())
            self.assertEqual(errs, [])
            self.assertEqual(cleaned["strict"],
                             sorted({"CAP_NET_RAW", "CAP_SYS_ADMIN",
                                     "CAP_SYS_PTRACE"}))
        finally:
            os.unlink(path)

    def test_root_must_be_dict(self):
        path = _write_policy(["not", "a", "dict"])
        try:
            with self.assertRaises(self.pl.PolicyError) as cm:
                self.pl._load_policy(path)
            self.assertIn("JSON object", str(cm.exception))
        finally:
            os.unlink(path)

    def test_missing_name_violates(self):
        p = _good_policy(); del p["name"]
        errs, _ = self.pl.validate_policy(p)
        self.assertTrue(any("name" in str(e) for e in errs))

    def test_blank_name_violates(self):
        errs, _ = self.pl.validate_policy(_good_policy(name="   "))
        self.assertTrue(any("name" in str(e) for e in errs))

    def test_bad_version_violates(self):
        errs, _ = self.pl.validate_policy(_good_policy(version="v1"))
        self.assertTrue(any("version" in str(e) for e in errs))

    def test_mem_below_minimum_violates(self):
        p = _good_policy()
        p["defaults"]["mem"] = "8K"
        errs, _ = self.pl.validate_policy(p)
        self.assertTrue(any("defaults.mem" in str(e) for e in errs))

    def test_mem_above_maximum_violates(self):
        p = _good_policy()
        p["defaults"]["mem"] = "2G"
        errs, _ = self.pl.validate_policy(p)
        self.assertTrue(any("defaults.mem" in str(e) for e in errs))

    def test_mem_unparseable_violates(self):
        p = _good_policy()
        p["defaults"]["mem"] = "lots"
        errs, _ = self.pl.validate_policy(p)
        self.assertTrue(any("defaults.mem" in str(e) for e in errs))

    def test_pids_out_of_range_violates(self):
        p = _good_policy()
        p["defaults"]["pids"] = 9999
        errs, _ = self.pl.validate_policy(p)
        self.assertTrue(any("defaults.pids" in str(e) for e in errs))

    def test_pids_zero_violates(self):
        p = _good_policy()
        p["defaults"]["pids"] = 0
        errs, _ = self.pl.validate_policy(p)
        self.assertTrue(any("defaults.pids" in str(e) for e in errs))

    def test_cpu_quota_out_of_range_violates(self):
        p = _good_policy()
        p["defaults"]["cpu_quota"] = 500
        errs, _ = self.pl.validate_policy(p)
        self.assertTrue(any("defaults.cpu_quota" in str(e) for e in errs))

    def test_timeout_too_long_violates(self):
        p = _good_policy()
        p["defaults"]["timeout"] = 7200
        errs, _ = self.pl.validate_policy(p)
        self.assertTrue(any("defaults.timeout" in str(e) for e in errs))

    def test_profile_name_uppercase_violates(self):
        p = _good_policy()
        p["profiles"]["Strict"] = []
        errs, _ = self.pl.validate_policy(p)
        self.assertTrue(any("profile name" in str(e).lower() or
                            "Strict" in str(e) for e in errs))

    def test_bad_cap_name_violates(self):
        p = _good_policy()
        p["profiles"]["strict"] = ["net_raw", "CAP_SYS_ADMIN"]
        errs, _ = self.pl.validate_policy(p)
        self.assertTrue(any("non-cap name" in str(e) for e in errs))

    def test_empty_profile_is_allowed(self):
        p = _good_policy()
        p["profiles"]["permissive"] = []
        errs, _ = self.pl.validate_policy(p)
        self.assertEqual(errs, [])

    def test_net_must_be_known(self):
        p = _good_policy()
        p["net"] = "loopback"
        errs, _ = self.pl.validate_policy(p)
        self.assertTrue(any("net" in str(e) for e in errs))

    def test_bad_env_name_violates(self):
        p = _good_policy()
        p["env_allowlist"] = ["path", "LANG"]
        errs, _ = self.pl.validate_policy(p)
        self.assertTrue(any("env_allowlist" in str(e) for e in errs))

    def test_readonly_must_be_bool(self):
        p = _good_policy()
        p["readonly"] = "yes"
        errs, _ = self.pl.validate_policy(p)
        self.assertTrue(any("readonly" in str(e) for e in errs))

    def test_caps_deduped_and_sorted(self):
        p = _good_policy()
        p["profiles"]["strict"] = ["CAP_SYS_ADMIN", "CAP_NET_RAW",
                                   "CAP_SYS_ADMIN"]
        _, cleaned = self.pl.validate_policy(p)
        self.assertEqual(cleaned["strict"],
                         ["CAP_NET_RAW", "CAP_SYS_ADMIN"])


class TestTranspile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pl = _load_module()

    def test_strict_profile_builds_cap_regex(self):
        p = _good_policy()
        _, cleaned = self.pl.validate_policy(p)
        argv = self.pl.transpile_argv(p, "strict", cleaned)
        # Default order is: --mem, --pids, --cpu-quota, --timeout,
        # --cap-drop. Assert presence + cap regex shape.
        self.assertIn("--cap-drop", argv)
        cap_idx = argv.index("--cap-drop")
        # Sorted alphabetically per validate_policy.
        self.assertEqual(argv[cap_idx + 1],
                         "CAP_(CAP_NET_RAW|CAP_SYS_ADMIN|CAP_SYS_PTRACE)")

    def test_permissive_profile_emits_never_match(self):
        p = _good_policy()
        _, cleaned = self.pl.validate_policy(p)
        argv = self.pl.transpile_argv(p, "permissive", cleaned)
        self.assertEqual(argv[argv.index("--cap-drop") + 1],
                         self.pl.NEVER_MATCH_CAP_REGEX)

    def test_unknown_profile_raises(self):
        p = _good_policy()
        _, cleaned = self.pl.validate_policy(p)
        with self.assertRaises(self.pl.PolicyError):
            self.pl.transpile_argv(p, "unknown", cleaned)

    def test_no_profile_omits_cap_drop(self):
        p = _good_policy()
        _, cleaned = self.pl.validate_policy(p)
        argv = self.pl.transpile_argv(p, None, cleaned)
        self.assertNotIn("--cap-drop", argv)


class TestCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pl = _load_module()

    def test_conformant_envelope_passes(self):
        p = _good_policy()
        _, cleaned = self.pl.validate_policy(p)
        env = {
            "exit_code": 0, "stdout": "", "stderr": "",
            "wall_clock_ms": 1500, "timeout_hit": False,
            "peak_mem_estimate": 50 * 1024 * 1024,
        }
        violations = self.pl.check_envelope_against_policy(p, env, cleaned)
        self.assertEqual(violations, [])

    def test_wall_clock_over_violates(self):
        p = _good_policy()
        p["defaults"]["timeout"] = 5
        _, cleaned = self.pl.validate_policy(p)
        env = {"wall_clock_ms": 12000, "timeout_hit": False,
               "peak_mem_estimate": None}
        violations = self.pl.check_envelope_against_policy(p, env, cleaned)
        self.assertTrue(any(v[0] == "wall_clock" for v in violations))

    def test_peak_mem_over_violates(self):
        p = _good_policy()
        p["defaults"]["mem"] = "128M"
        _, cleaned = self.pl.validate_policy(p)
        env = {"wall_clock_ms": 1000, "timeout_hit": False,
               "peak_mem_estimate": 200 * 1024 * 1024}
        violations = self.pl.check_envelope_against_policy(p, env, cleaned)
        self.assertTrue(any(v[0] == "peak_mem" for v in violations))

    def test_timeout_hit_always_violates(self):
        p = _good_policy()
        _, cleaned = self.pl.validate_policy(p)
        env = {"wall_clock_ms": 1000, "timeout_hit": True}
        violations = self.pl.check_envelope_against_policy(p, env, cleaned)
        self.assertTrue(any(v[0] == "timeout_hit" for v in violations))

    def test_malformed_envelope_violates(self):
        p = _good_policy()
        _, cleaned = self.pl.validate_policy(p)
        violations = self.pl.check_envelope_against_policy(p, "string",
                                                            cleaned)
        self.assertTrue(any(v[0] == "malformed" for v in violations))


class TestMainDispatch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pl = _load_module()

    def _ok_envelope(self):
        return json.dumps({
            "exit_code": 0, "stdout": "", "stderr": "",
            "wall_clock_ms": 1000, "timeout_hit": False,
            "peak_mem_estimate": 1024 * 1024,
        })

    def test_validate_dispatches(self):
        path = _write_policy(_good_policy())
        try:
            with mock.patch.object(sys, "stdout", io.StringIO()):
                rc = self.pl.main(["validate", path])
            self.assertEqual(rc, 0)
        finally:
            os.unlink(path)

    def test_validate_text_reports_violations(self):
        bad = _good_policy()
        bad["defaults"]["mem"] = "lots"
        path = _write_policy(bad)
        try:
            buf = io.StringIO()
            with mock.patch.object(sys, "stdout", buf), \
                 mock.patch.object(sys, "stderr", buf):
                rc = self.pl.main(["validate", path])
            self.assertEqual(rc, 1)
            self.assertIn("violation", buf.getvalue())
        finally:
            os.unlink(path)

    def test_validate_json_envelope_shape(self):
        path = _write_policy(_good_policy())
        try:
            buf = io.StringIO()
            with mock.patch.object(sys, "stdout", buf), \
                 mock.patch.object(sys, "stderr", buf):
                rc = self.pl.main(["validate", "--json", path])
            self.assertEqual(rc, 0)
            line = buf.getvalue().strip()
            obj = json.loads(line)
            self.assertTrue(obj["ok"])
            self.assertEqual(obj["errors"], [])
            self.assertEqual(obj["name"], "neuros-default")
        finally:
            os.unlink(path)

    def test_check_passes(self):
        p_path = _write_policy(_good_policy())
        e_path = _write_policy(json.loads(self._ok_envelope()))
        try:
            with mock.patch.object(sys, "stdout", io.StringIO()):
                rc = self.pl.main(["check", p_path, "--envelope", e_path])
            self.assertEqual(rc, 0)
        finally:
            os.unlink(p_path); os.unlink(e_path)

    def test_check_fails_on_violation(self):
        bad_env = json.loads(self._ok_envelope())
        bad_env["wall_clock_ms"] = 999_999  # exceeds 30s default
        p_path = _write_policy(_good_policy())
        e_path = _write_policy(bad_env)
        try:
            buf = io.StringIO()
            with mock.patch.object(sys, "stdout", buf), \
                 mock.patch.object(sys, "stderr", buf):
                rc = self.pl.main(["check", p_path, "--envelope", e_path])
            self.assertEqual(rc, 1)
        finally:
            os.unlink(p_path); os.unlink(e_path)

    def test_transpile_emits_argv_text(self):
        path = _write_policy(_good_policy())
        try:
            buf = io.StringIO()
            with mock.patch.object(sys, "stdout", buf), \
                 mock.patch.object(sys, "stderr", io.StringIO()):
                rc = self.pl.main(["transpile", path,
                                   "--profile", "strict"])
            self.assertEqual(rc, 0)
            txt = buf.getvalue().strip()
            self.assertIn("--mem 256M", txt)
            self.assertIn("--pids 64", txt)
            self.assertIn("--cpu-quota 50000", txt)
            self.assertIn("--cap-drop CAP_(", txt)
        finally:
            os.unlink(path)

    def test_transpile_refuses_invalid_policy(self):
        bad = _good_policy()
        bad["name"] = ""
        path = _write_policy(bad)
        try:
            buf = io.StringIO()
            with mock.patch.object(sys, "stdout", buf), \
                 mock.patch.object(sys, "stderr", buf):
                rc = self.pl.main(["transpile", path])
            self.assertEqual(rc, 1)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
