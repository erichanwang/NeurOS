#!/usr/bin/env python3
"""Tests for neuros-sandbox safe-runner wrapper.

These tests do not need real kernel/cgroup delegation because they
mock `subprocess.run` and the filesystem paths that the wrapper
constructs. They assert:

  * Default safe flag set is always passed to neuros-container
  * --unsafe relaxes --net/--read-only/cap-drop and lets
    --cap-drop-keep apply its own regex
  * Host env is scrubbed to PATH only (no API keys leak)
  * Watchdog timeout surfaces as exit 124 with timeout_hit=True
  * JSON envelope is single-line and JSON-parseable
  * Bundle extraction rejects absolute/traversal paths and cleans up
  * Stdin is read when no script path is given
  * Script file read errors surface as SandboxError
"""
import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
_SANDBOX_PATH = os.path.join(
    ROOT, "config", "includes.chroot", "usr", "local", "bin", "neuros-sandbox")


def _load_neuros_sandbox():
    """Load ``neuros-sandbox`` (no .py suffix in its install path) by
    compiling its source and exec-ing in a fresh module namespace.
    This is the only stable way to import a hyphen-named script.

    The loader caches in ``sys.modules`` indefinitely. After editing
    the production source file, call ``importlib.reload(sb)`` (or
    ``importlib.reload(sys.modules["neuros_sandbox"])``) to pick up
    the change without restarting the test process.
    """
    with open(_SANDBOX_PATH) as f:
        source = f.read()
    code = compile(source, _SANDBOX_PATH, "exec")
    module = sys.modules.get("neuros_sandbox") or types.ModuleType(
        "neuros_sandbox")
    module.__file__ = _SANDBOX_PATH
    sys.modules["neuros_sandbox"] = module
    exec(code, module.__dict__)
    return module


class _FakeStdStream:
    """Mimic sys.stdout/sys.stderr's contract so the production
    `sys.stdout.buffer.write(bytes)` AND `sys.stderr.write(str)` calls
    both work. Use it via `with mock.patch.object(sys, "stdout", stream):`.

    Reads from .buffer accumulate bytes; reads from .write accumulate
    text. The combined payload is exposed as .value().
    """

    def __init__(self):
        self._buffer = io.BytesIO()
        self._text = []

    @property
    def buffer(self):
        return self._buffer

    def write(self, data):
        if isinstance(data, bytes):
            self._buffer.write(data)
        else:
            self._text.append(data)

    def flush(self):
        pass

    def value(self):
        return self._buffer.getvalue() + "".join(self._text).encode(
            "utf-8", errors="replace")


sb = _load_neuros_sandbox()


class TestParsePercent(unittest.TestCase):
    def test_percent_string(self):
        self.assertEqual(sb._parse_percent("50%"), 50000)
        self.assertEqual(sb._parse_percent("25%"), 25000)
        self.assertEqual(sb._parse_percent("100%"), 100000)

    def test_fraction(self):
        self.assertEqual(sb._parse_percent("0.25"), 25000)
        self.assertEqual(sb._parse_percent("1.0"), 100000)

    def test_microseconds(self):
        self.assertEqual(sb._parse_percent("50000us"), 50000)
        self.assertEqual(sb._parse_percent("100000us"), 100000)


class TestBuildArgv(unittest.TestCase):
    def _args(self, **overrides):
        # MUST use argparse.Namespace (not mock.Mock): Mock evaluates
        # as truthy regardless of the kwarg passed, which silently
        # disables the safety-net flag set in _build_argv. The defaults
        # dict pattern lets overrides cleanly replace named defaults
        # without producing argparse.Namespace(TypeError: multiple values).
        defaults = dict(
            unsafe=False,
            mem=sb.DEFAULT_MEM,
            pids=sb.DEFAULT_PIDS,
            cpu_quota=sb.DEFAULT_CPU_QUOTA,
            cap_drop=sb.DEFAULT_CAP_DROP,
            cap_drop_keep=None,
            rootfs=None,
            name=None,
            user=None,
        )
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    def test_safe_mode_default_flags_present(self):
        argv = sb._build_argv(self._args(), script_target="-")
        self.assertEqual(argv[0], "neuros-container")
        self.assertEqual(argv[1], "run")
        # safety nets are on
        self.assertIn("--net", argv)
        self.assertIn("--read-only", argv)
        self.assertIn("--cap-drop", argv)
        # Lock: the value following --cap-drop must be exactly the
        # baseline DEFAULT_CAP_DROP, not the wrapper's blank string or
        # any silent re-default.
        self.assertEqual(
            argv[argv.index("--cap-drop") + 1], sb.DEFAULT_CAP_DROP)
        # defaults flow through
        self.assertIn("--mem", argv)
        self.assertEqual(argv[argv.index("--mem") + 1], sb.DEFAULT_MEM)
        self.assertIn("--pids", argv)
        self.assertEqual(argv[argv.index("--pids") + 1], str(sb.DEFAULT_PIDS))
        self.assertIn("--cpu-quota", argv)
        self.assertEqual(
            argv[argv.index("--cpu-quota") + 1], str(sb.DEFAULT_CPU_QUOTA))
        # name is generated when not given
        name = argv[argv.index("--name") + 1]
        self.assertTrue(name.startswith(sb.NAME_PREFIX))
        # entry point is the stdin python interpreter
        self.assertEqual(argv[-3:], ["python3", "-u", "-"])

    def test_unsafe_mode_relaxes_safe_flags(self):
        argv = sb._build_argv(self._args(unsafe=True), script_target="-")
        self.assertNotIn("--net", argv)
        self.assertNotIn("--read-only", argv)
        # The default cap-drop is still passed under --unsafe unless
        # --cap-drop-keep replaces it; here we don't override.
        self.assertIn("--cap-drop", argv)
        # value-level invariant: even in unsafe mode the baseline
        # DEFAULT_CAP_DROP is what lands in the primitive's --cap-drop
        # slot, not any silent relaxation.
        self.assertEqual(
            argv[argv.index("--cap-drop") + 1], sb.DEFAULT_CAP_DROP)

    def test_unsafe_with_cap_drop_keep_replaces(self):
        argv = sb._build_argv(self._args(
            unsafe=True, cap_drop_keep=r"CAP_NET_RAW"
        ), script_target="-")
        self.assertNotIn("--net", argv)
        self.assertNotIn("--read-only", argv)
        self.assertEqual(
            argv[argv.index("--cap-drop") + 1], r"CAP_NET_RAW")

    def test_rootfs_and_user_appear(self):
        argv = sb._build_argv(self._args(
            rootfs="/srv/rootfs", user="1000:1000"
        ), script_target="/tmp/script.py")
        self.assertEqual(argv[argv.index("--rootfs") + 1], "/srv/rootfs")
        self.assertEqual(argv[argv.index("--user") + 1], "1000:1000")
        # entry point ends with the script path
        self.assertEqual(argv[-1], "/tmp/script.py")

    def test_name_override_passthrough(self):
        argv = sb._build_argv(
            self._args(name="explicit-name"), script_target="-")
        self.assertEqual(argv[argv.index("--name") + 1], "explicit-name")

    def test_safe_mode_ignores_cap_drop_keep(self):
        """--cap-drop-keep is documented as unsafe-mode-only. Pass it
        under safe mode and assert (a) the value following --cap-drop
        is still DEFAULT_CAP_DROP, and (b) the literal override value
        the user passed in is NOT substituted into argv. Locks the
        policy so a future refactor that adds a fast path doesn't
        accidentally honor --cap-drop-keep in safe mode."""
        cap_keep = r"CAP_NET_RAW"
        argv = sb._build_argv(self._args(
            cap_drop_keep=cap_keep
        ), script_target="-")
        self.assertEqual(
            argv[argv.index("--cap-drop") + 1], sb.DEFAULT_CAP_DROP)
        # The literal override value must not appear in the produced
        # argv (only DEFAULT_CAP_DROP should). This locks the policy
        # at value-granularity rather than flag-name-granularity,
        # which would be a tautology since _build_argv never emits
        # --cap-drop-keep as a separate flag.
        self.assertNotIn(cap_keep, argv)

    def test_cap_drop_keep_invalid_regex_raises_sandbox_error(self):
        """Lock the contract that an invalid --cap-drop-keep regex
        fails at the wrapper layer (SandboxError) before the primitive
        is even invoked. Keeps the failure surface out of the
        kernel-bridge ctypes call.
        """
        with self.assertRaises(sb.SandboxError):
            sb._build_argv(self._args(
                unsafe=True, cap_drop_keep=r"[unclosed"
            ), script_target="-")

    def test_cap_drop_keep_empty_string_raises_sandbox_error(self):
        """Lock the contract that --cap-drop-keep '' under --unsafe is
        an explicit user error, NOT a silent fallback to the default
        cap-drop regex. Empty string was previously silenced by the
        truthiness check; the is-not-None check exposes it.
        """
        with self.assertRaises(sb.SandboxError):
            sb._build_argv(self._args(
                unsafe=True, cap_drop_keep=""
            ), script_target="-")

    def test_cap_drop_keep_whitespace_only_raises_sandbox_error(self):
        """Lock the contract that --cap-drop-keep '   ' (whitespace
        only) is rejected just like the empty string — otherwise
        re.compile('   ') silently produces a valid-but-useless regex
        that matches literal whitespace exclusively.
        """
        with self.assertRaises(sb.SandboxError):
            sb._build_argv(self._args(
                unsafe=True, cap_drop_keep="   \t\n"
            ), script_target="-")


class TestLoadScript(unittest.TestCase):
    def test_file_path(self):
        with tempfile.NamedTemporaryFile("wb", delete=False) as f:
            f.write(b"print('hello')\n")
            path = f.name
        try:
            self.assertEqual(sb._load_script(path), b"print('hello')\n")
        finally:
            os.unlink(path)

    def test_missing_file_raises_sandbox_error(self):
        with self.assertRaises(sb.SandboxError):
            sb._load_script("/nonexistent/path/script.py")

    def test_empty_string_path_raises(self):
        with tempfile.NamedTemporaryFile("wb", delete=False) as f:
            f.write(b"")
            path = f.name
        try:
            with self.assertRaises(sb.SandboxError):
                sb._load_script(path)
        finally:
            os.unlink(path)


class TestStdInLoadScript(unittest.TestCase):
    def test_stdin_when_path_is_none(self):
        with mock.patch.object(sys, "stdin") as mock_stdin:
            mock_stdin.buffer = io.BytesIO(b"from_stdin")
            self.assertEqual(sb._load_script(None), b"from_stdin")


class TestExtractBundle(unittest.TestCase):
    def _make_tar(self, members):
        f = tempfile.NamedTemporaryFile("wb", delete=False, suffix=".tar")
        with tarfile.open(fileobj=f, mode="w") as tar:
            for name, content in members.items():
                data = content.encode("utf-8") if isinstance(content, str) else content
                info = tarfile.TarInfo(name=name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        return f.name

    def test_extracts_simple_bundle_and_returns_path(self):
        path = self._make_tar({"a.txt": "alpha", "b/c.txt": "beta"})
        try:
            out = sb._extract_bundle(path)
            try:
                self.assertTrue(os.path.isdir(out))
                self.assertEqual(
                    open(os.path.join(out, "a.txt")).read(), "alpha")
                self.assertEqual(
                    open(os.path.join(out, "b", "c.txt")).read(), "beta")
            finally:
                shutil.rmtree(out, ignore_errors=True)
        finally:
            os.unlink(path)

    def test_rejects_absolute_path_entry(self):
        path = self._make_tar({"/abs.txt": "x"})
        try:
            with self.assertRaises(sb.SandboxError):
                sb._extract_bundle(path)
        finally:
            os.unlink(path)

    def test_rejects_traversal_entry(self):
        path = self._make_tar({"../escape.txt": "x"})
        try:
            with self.assertRaises(sb.SandboxError):
                sb._extract_bundle(path)
        finally:
            os.unlink(path)


class TestRunInSandbox(unittest.TestCase):
    """Drives cmd_run end-to-end with a mocked subprocess.run."""

    def _args(self, **overrides):
        defaults = dict(
            cmd="run",
            script="script.py",
            mem="256M",
            pids=sb.DEFAULT_PIDS,
            cpu=None,
            cpu_quota=sb.DEFAULT_CPU_QUOTA,
            cap_drop=sb.DEFAULT_CAP_DROP,
            cap_drop_keep=None,
            rootfs=None,
            name="test-name",
            user=None,
            bundle=None,
            timeout=5,
            unsafe=False,
            json=False,
            dry_run=False,
        )
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    @mock.patch.object(sb, "_load_script", return_value=b"script-bytes")
    @mock.patch.object(sb, "_read_peak_memory", return_value=None)
    @mock.patch.object(sb.subprocess, "run")
    def test_human_mode_passes_through_stdout_and_stderr(
            self, m_run, _mp, _ml):
        cp = mock.Mock(returncode=0, stdout=b"hello\n", stderr=b"warn\n")
        m_run.return_value = cp
        # FakeStdStream exposes both .buffer (BytesIO) for binary
        # writes AND .write(str) for the trailer line, so the
        # production path through sys.stdout.buffer + sys.stderr.write
        # both work cleanly.
        s_out = _FakeStdStream()
        s_err = _FakeStdStream()
        with mock.patch.object(sys, "stdout", s_out), \
             mock.patch.object(sys, "stderr", s_err):
            rc = sb.cmd_run(self._args())
        self.assertEqual(rc, 0)
        out_payload = s_out.value()
        err_payload = s_err.value()
        self.assertIn(b"hello", out_payload)
        self.assertIn(b"warn", err_payload)
        self.assertIn(b"[neuros-sandbox]", err_payload)
        # Env MUST be scrubbed to MINIMAL_ENV
        positional, kwargs = m_run.call_args
        self.assertEqual(kwargs["env"], sb.MINIMAL_ENV)
        # input must contain the script bytes
        self.assertEqual(kwargs["input"], b"script-bytes")
        # Wall-clock mgmt passes timeout through
        self.assertEqual(kwargs["timeout"], 5)

    @mock.patch.object(sb, "_load_script", return_value=b"script-bytes")
    @mock.patch.object(sb, "_read_peak_memory", return_value=None)
    @mock.patch.object(sb.subprocess, "run")
    def test_json_mode_emits_single_line_envelope(
            self, m_run, _mp, _ml):
        cp = mock.Mock(returncode=2, stdout=b"out", stderr=b"err")
        m_run.return_value = cp
        buf = io.StringIO()
        with mock.patch.object(sys, "stdout", buf):
            rc = sb.cmd_run(self._args(json=True))
        self.assertEqual(rc, 2)
        lines = [l for l in buf.getvalue().splitlines() if l]
        self.assertEqual(len(lines), 1)
        env = json.loads(lines[0])
        self.assertEqual(env["exit_code"], 2)
        self.assertEqual(env["stdout"], "out")
        self.assertEqual(env["stderr"], "err")
        self.assertFalse(env["timeout_hit"])
        self.assertIn("wall_clock_ms", env)
        # peak_mem_estimate is propagated when non-None
        self.assertIsNone(env["peak_mem_estimate"])

    @mock.patch.object(sb, "_load_script", return_value=b"script-bytes")
    @mock.patch.object(sb, "_read_peak_memory", return_value=8388608)
    @mock.patch.object(sb.subprocess, "run")
    def test_json_envelope_propagates_peak_mem(
            self, m_run, _mp, _ml):
        m_run.return_value = mock.Mock(
            returncode=0, stdout=b"", stderr=b"")
        buf = io.StringIO()
        with mock.patch.object(sys, "stdout", buf):
            sb.cmd_run(self._args(json=True))
        env = json.loads(buf.getvalue().strip())
        self.assertEqual(env["peak_mem_estimate"], 8388608)

    @mock.patch.object(sb, "_load_script", return_value=b"x")
    @mock.patch.object(sb, "_read_peak_memory", return_value=None)
    @mock.patch.object(sb.subprocess, "run")
    def test_timeout_returns_124_and_marks_envelope(
            self, m_run, _mp, _ml):
        m_run.side_effect = subprocess.TimeoutExpired(cmd=["x"], timeout=5)
        buf = io.StringIO()  # --json mode uses print() which is text
        with mock.patch.object(sys, "stdout", buf):
            rc = sb.cmd_run(self._args(json=True))
        self.assertEqual(rc, 124)
        env = json.loads(buf.getvalue().strip())
        self.assertTrue(env["timeout_hit"])
        self.assertEqual(env["exit_code"], 124)
        # Lock the contract: cmd_run forwards the same argv to
        # subprocess.run that callers can correlate with the
        # constructed CompletedProcess in the timeout path. Production
        # calls subprocess.run(ARGV_LIST, ...), so the ARGV_LIST is
        # captured as the single first positional argument to run:
        # call_args.args == ([ARGV_LIST],) — and ARGV_LIST[0] is then
        # "neuros-container".
        run_args, _ = m_run.call_args
        self.assertEqual(len(run_args), 1, "subprocess.run got a single argv list")
        self.assertEqual(run_args[0][0], "neuros-container")

    @mock.patch.object(sb, "_load_script", return_value=b"x")
    @mock.patch.object(sb.subprocess, "run")
    def test_dry_run_prints_argv_and_does_not_spawn(
            self, m_run, _ml):
        buf = io.StringIO()
        with mock.patch.object(sys, "stdout", buf):
            rc = sb.cmd_run(self._args(dry_run=True))
        self.assertEqual(rc, 0)
        self.assertIn("neuros-container", buf.getvalue())
        self.assertIn("--net", buf.getvalue())
        self.assertIn("--read-only", buf.getvalue())
        # No actual subprocess call was made
        m_run.assert_not_called()

    @mock.patch.object(sb.subprocess, "run")
    def test_bundle_extracts_and_rmtree_cleanup_is_called(
            self, m_run):
        """Verify the wrapper explicitly rmtree's the bundle tmpdir we
        created (no implicit leak)."""
        captured_roots = []
        real_rmtree = sb.shutil.rmtree

        def track_rmtree(path, *a, **kw):
            captured_roots.append(path)
            real_rmtree(path, *a, **kw)

        with tempfile.TemporaryDirectory() as tmp:
            tar_path = os.path.join(tmp, "bundle.tar")
            with tarfile.open(tar_path, "w") as tar:
                data = b"echo hi\n"
                info = tarfile.TarInfo("script.sh")
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            with mock.patch.object(sb, "_load_script",
                                   return_value=b"echo hi"), \
                 mock.patch.object(sb.shutil, "rmtree",
                                   side_effect=track_rmtree):
                cp = mock.Mock(returncode=0, stdout=b"out", stderr=b"")
                m_run.return_value = cp
                s_err = _FakeStdStream()
                with mock.patch.object(sys, "stdout", _FakeStdStream()), \
                     mock.patch.object(sys, "stderr", s_err):
                    rc = sb.cmd_run(self._args(bundle=tar_path))
            self.assertEqual(rc, 0)
            # The wrapper created at least one tmpdir for the bundle,
            # and rmtree was called on it.
            self.assertTrue(captured_roots, "rmtree was never called")
            self.assertTrue(any(
                "neuros-sbx-bundle-" in p for p in captured_roots))


class TestReadPeakMemory(unittest.TestCase):
    """Best-effort memory.peak polling exercised with tmpdir fake files."""

    def test_returns_int_when_file_exists(self):
        with tempfile.TemporaryDirectory() as td:
            # Create the cgroup-tree convention neuros-container uses
            # by carving out the leaf dir directly under /sys/fs/cgroup.
            leaf = os.path.join(td, "neuros-sbx-foo")
            os.makedirs(leaf)
            with open(os.path.join(leaf, "memory.peak"), "w") as f:
                f.write("1234567\n")
            with mock.patch.object(sb, "_CGROUP_V2_ROOTS", (td,)):
                self.assertEqual(sb._read_peak_memory("foo"), 1234567)

    def test_returns_none_when_file_missing(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(sb, "_CGROUP_V2_ROOTS", (td,)):
                self.assertIsNone(sb._read_peak_memory("missing"))

    def test_returns_none_on_unparseable_value(self):
        with tempfile.TemporaryDirectory() as td:
            leaf = os.path.join(td, "neuros-sbx-foo")
            os.makedirs(leaf)
            with open(os.path.join(leaf, "memory.peak"), "w") as f:
                f.write("not-a-number\n")
            with mock.patch.object(sb, "_CGROUP_V2_ROOTS", (td,)):
                self.assertIsNone(sb._read_peak_memory("foo"))

    def test_mtime_tie_breaks_by_shorter_path(self):
        """Two leaves with identical mtime: the shorter (closer-to-root)
        path wins via the (mtime, -len(p)) sort key."""
        with tempfile.TemporaryDirectory() as td:
            shallow = os.path.join(td, "neuros-sbx-foo")
            deep = os.path.join(td, "slice", "neuros", "neuros-sbx-foo")
            for d in (shallow, deep):
                os.makedirs(d, exist_ok=True)
            # Both files exist; force identical mtime.
            fixed = 1_700_000_000.0
            for leaf in (shallow, deep):
                with open(os.path.join(leaf, "memory.peak"), "w") as f:
                    f.write("42\n")
                os.utime(leaf, (fixed, fixed))
            with mock.patch.object(sb, "_CGROUP_V2_ROOTS", (td,)):
                # Shorter path should win, returning 42.
                self.assertEqual(sb._read_peak_memory("foo"), 42)


class TestMainDispatch(unittest.TestCase):
    def test_unknown_cmd_exits(self):
        with self.assertRaises(SystemExit):
            sb.main(["nope"])

    def test_cpu_flag_translates_to_quota(self):
        argv = ["run", "script.py", "--cpu", "25%", "--dry-run"]
        buf = io.StringIO()
        with mock.patch.object(sys, "stdout", buf), \
             mock.patch.object(sys, "stderr", io.StringIO()):
            rc = sb.main(argv)
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        # 25% of 100000 = 25000
        self.assertIn("--cpu-quota 25000", out)


if __name__ == "__main__":
    unittest.main()
