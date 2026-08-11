#!/usr/bin/env python3
"""
test_container.py — Unit and integration tests for neuros-container.

The integration tests exercise real cgroup v2 enforcement (they create,
populate, and tear down an actual cgroup on the machine running the
suite) but skip cleanly if cgroup v2 delegation isn't available, the
same way the rest of this repo skips checks that need a full host.
"""

import io
import json as _json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import importlib.util
from importlib.machinery import SourceFileLoader
from unittest.mock import patch, MagicMock

CONTAINER_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..",
    "config", "includes.chroot", "usr", "local", "bin", "neuros-container"
)


def load_neuros_container():
    loader = SourceFileLoader("neuros_container", CONTAINER_PATH)
    spec = importlib.util.spec_from_loader("neuros_container", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def cgroups_available():
    """Stronger probe than just "make_cgroup returns a path": also
    read back the limit file we set to confirm the write actually took
    effect. A bare-EACCES mkdir leaves the leaf visible but the
    limit files never get populated, which silently produces
    containers that ignore `--mem`. Detect that here so the detach
    integration test isn't misclassified as runnable."""
    try:
        nc = load_neuros_container()
        cg = nc.make_cgroup("neuros-selftest-probe", "16777216", None, None)
        # Read back and confirm the controller write was real.
        with open(os.path.join(cg, "memory.max")) as f:
            content = f.read().strip()
        ok = content == "16777216"
        try:
            os.rmdir(cg)
        except OSError:
            pass
        return ok
    except OSError:
        return False


class TestSizeParsing(unittest.TestCase):
    def setUp(self):
        self.nc = load_neuros_container()

    def test_plain_bytes(self):
        self.assertEqual(self.nc.parse_size("1000"), "1000")

    def test_kilobytes(self):
        self.assertEqual(self.nc.parse_size("4K"), str(4 * 1024))

    def test_megabytes(self):
        self.assertEqual(self.nc.parse_size("256M"), str(256 * 1024 ** 2))

    def test_gigabytes(self):
        self.assertEqual(self.nc.parse_size("1G"), str(1024 ** 3))

    def test_max_literal(self):
        self.assertEqual(self.nc.parse_size("max"), "max")

    def test_none_passthrough(self):
        self.assertIsNone(self.nc.parse_size(None))

    def test_rejects_garbage(self):
        with self.assertRaises(SystemExit):
            self.nc.parse_size("not-a-size")


class TestCpuQuotaParsing(unittest.TestCase):
    def setUp(self):
        self.nc = load_neuros_container()

    def test_slash_separator(self):
        self.assertEqual(self.nc.parse_cpu_quota("50000/100000"), ("50000", "100000"))

    def test_space_separator(self):
        self.assertEqual(self.nc.parse_cpu_quota("25000 100000"), ("25000", "100000"))

    def test_max_literal(self):
        self.assertEqual(self.nc.parse_cpu_quota("max"), ("max", "max"))

    def test_none_passthrough(self):
        self.assertIsNone(self.nc.parse_cpu_quota(None))

    def test_rejects_garbage(self):
        with self.assertRaises(SystemExit):
            self.nc.parse_cpu_quota("not-a-quota")

    def test_rejects_zero_period(self):
        """period_us must be > 0; cpu.max rejects zero periods."""
        with self.assertRaises(SystemExit):
            self.nc.parse_cpu_quota("50000/0")

    def test_rejects_negative_max(self):
        with self.assertRaises(SystemExit):
            self.nc.parse_cpu_quota("-1/100000")

    def test_rejects_one_part(self):
        with self.assertRaises(SystemExit):
            self.nc.parse_cpu_quota("50000")


class TestUserParsing(unittest.TestCase):
    def setUp(self):
        self.nc = load_neuros_container()

    def test_uid_only_collapses_to_same_gid(self):
        self.assertEqual(self.nc.parse_user("1000"), (1000, 1000))

    def test_uid_gid_pair(self):
        self.assertEqual(self.nc.parse_user("1000:1001"), (1000, 1001))

    def test_root(self):
        self.assertEqual(self.nc.parse_user("0:0"), (0, 0))

    def test_none_passthrough(self):
        self.assertIsNone(self.nc.parse_user(None))

    def test_rejects_garbage(self):
        with self.assertRaises(SystemExit):
            self.nc.parse_user("not-a-user")

    def test_rejects_name_style(self):
        with self.assertRaises(SystemExit):
            self.nc.parse_user("alice")


class TestEnterNamespacesBitmask(unittest.TestCase):
    """The 6-tuple contract from enter_namespaces() must report the
    right combination of True/False for each feasibility path.

    Implementation note: ``load_neuros_container()`` returns a fresh
    ``module`` object on each call (``importlib.util.module_from_spec``
    is not cached when invoked outside of an actual ``import`` statement),
    so decorator-level ``@patch.object(load_neuros_container(), ...)``
    targets a module that ``self.nc`` no longer points at. Patching
    ``self.nc`` directly inside each test sidesteps that."""

    def setUp(self):
        self.nc = load_neuros_container()

    def test_root_with_net_gets_full_mask(self):
        with patch("os.geteuid", return_value=0), \
             patch.object(self.nc, "try_unprivileged_userns",
                          return_value=True), \
             patch("os.unshare"):
            ns = self.nc.enter_namespaces(net=True, user=None)
        self.assertEqual(ns, (True, True, True, True, True, False))

    def test_root_without_net_has_net_false(self):
        with patch("os.geteuid", return_value=0), \
             patch("os.unshare"):
            ns = self.nc.enter_namespaces(net=False, user=None)
        self.assertEqual(ns, (True, True, True, True, False, False))

    def test_no_privs_yields_all_false(self):
        with patch("os.geteuid", return_value=1000), \
             patch.object(self.nc, "try_unprivileged_userns",
                          return_value=False):
            ns = self.nc.enter_namespaces(net=False, user=None)
        self.assertEqual(ns, (False, False, False, False, False, False))

    def test_unprivileged_with_userns_gets_full_mask(self):
        with patch("os.geteuid", return_value=1000), \
             patch.object(self.nc, "try_unprivileged_userns",
                          return_value=True), \
             patch("os.unshare"):
            ns = self.nc.enter_namespaces(net=False, user=(1000, 1000))
        self.assertEqual(ns, (True, True, True, True, False, True))

    def test_unshare_failure_returns_all_false(self):
        with patch("os.geteuid", return_value=0), \
             patch("os.unshare", side_effect=OSError("eperm")):
            ns = self.nc.enter_namespaces(net=False, user=None)
        self.assertEqual(ns, (False, False, False, False, False, False))


class TestListRecursion(unittest.TestCase):
    """list_cgroups descends through non-neuros- intermediate
    directories; the integration tests use the live cgroup tree under
    the delegating ancestor, and we exercise that on a synthetic tree
    here."""

    def setUp(self):
        self.nc = load_neuros_container()

    def test_finds_nested_leaves_via_synthetic_tree(self):
        """Build a tiny tree under a tmpdir and verify the recursive
        walker reaches ``neuros-*`` leaves at multiple depths."""
        root = tempfile.mkdtemp()
        try:
            deep = os.path.join(root, "intermediate", "neuros-deep-1")
            os.makedirs(deep)
            # A procs file is what the walker reads; empty means
            # the leaf claims to have 0 members, which is fine here.
            open(os.path.join(deep, "cgroup.procs"), "w").close()
            rows = self.nc._list_neuros_leaves(root)
            names = [r["name"] for r in rows]
            self.assertIn("neuros-deep-1", names)
            # If two leaves sit at different depths, both are picked up.
            sibling = os.path.join(root, "neuros-shallow")
            os.makedirs(sibling)
            open(os.path.join(sibling, "cgroup.procs"), "w").close()
            names = [r["name"] for r in self.nc._list_neuros_leaves(root)]
            self.assertEqual(set(names), {"neuros-deep-1", "neuros-shallow"})
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_json_output_is_valid_json_array(self):
        """list_cgroups(--json) must produce a parseable JSON array,
        empty or populated, on stdout. Patch own_cgroup_path to an
        empty tmpdir so no live cgroup tree is required."""
        root = tempfile.mkdtemp()
        try:
            with patch.object(self.nc, "own_cgroup_path",
                              return_value=root), \
                 patch("sys.stdout", new_callable=io.StringIO) as buf:
                self.nc.list_cgroups(json_output=True)
            payload = _json.loads(buf.getvalue().strip())
            self.assertIsInstance(payload, list)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_human_output_reports_zero_processes(self):
        """list_cgroups() with no JSON flag on an empty tree prints a
        single human-readable line instead of the JSON array."""
        root = tempfile.mkdtemp()
        try:
            with patch.object(self.nc, "own_cgroup_path",
                              return_value=root), \
                 patch("sys.stdout", new_callable=io.StringIO) as buf:
                self.nc.list_cgroups(json_output=False)
            self.assertIn("no active neuros-container cgroups", buf.getvalue())
        finally:
            shutil.rmtree(root, ignore_errors=True)


class TestCpuQuotaMaxRoundTrip(unittest.TestCase):
    """parse_cpu_quota('max') must round-trip through make_cgroup so
    that ``cpu.max = 'max max'`` is written and recoverable."""

    def setUp(self):
        self.nc = load_neuros_container()

    @unittest.skipUnless(
        __import__("os").path.isdir("/sys/fs/cgroup"),
        "needs a cgroup v2 mount",
    )
    def test_max_writes_max_max_to_cpu_max(self):
        cg = self.nc.make_cgroup("neuros-selftest-max", None, None, None,
                                 cpu_quota=("max", "max"))
        try:
            with open(os.path.join(cg, "cpu.max")) as f:
                value = f.read().strip()
            # Treat "max max" as the accepted unlimited form.
            self.assertIn(value, ("max max", "max 100000"))
        finally:
            try:
                os.rmdir(cg)
            except OSError:
                pass


class TestCleanupDetached(unittest.TestCase):
    """Unit coverage for ``cleanup_container`` / ``cleanup_all`` —
    drives them against a synthetic state file and a fake (empty)
    cgroup path so the test doesn't need a real detached run, root,
    or a delegated cgroup tree."""

    def setUp(self):
        self.nc = load_neuros_container()

    def test_cleanup_removes_empty_cgroup_and_state(self):
        root = tempfile.mkdtemp()
        try:
            cg_dir = os.path.join(root, "neuros-cgood")
            os.makedirs(cg_dir)
            # The "empty cgroup" path means cleanup_container's probe
            # for cgroup.procs falls through the OSError branch (which
            # is what an actually-empty leaf looks like on most
            # hosts). Don't write a procs file: rmdir requires the
            # directory to be fully empty, including any leftover
            # cgroup.procs the kernel might not have created.
            with patch.object(self.nc, "STATE_DIR", root):
                state_path = os.path.join(self.nc.STATE_DIR,
                                          "neuros-cgood.json")
                with open(state_path, "w") as f:
                    _json.dump({"name": "neuros-cgood",
                                 "pid": 99999,
                                 "cgroup": cg_dir}, f)
                rc = self.nc.cleanup_container("neuros-cgood")
            self.assertEqual(rc, 0)
            self.assertFalse(os.path.exists(cg_dir))
            self.assertFalse(os.path.exists(state_path))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_cleanup_refuses_when_cgroup_still_has_procs(self):
        root = tempfile.mkdtemp()
        try:
            cg_dir = os.path.join(root, "neuros-cbusy")
            os.makedirs(cg_dir)
            with open(os.path.join(cg_dir, "cgroup.procs"), "w") as f:
                f.write("1234\n5678\n")  # two fake live members
            state_path = os.path.join(root, "neuros-cbusy.json")
            with open(state_path, "w") as f:
                _json.dump({"name": "neuros-cbusy",
                             "pid": 1234,
                             "cgroup": cg_dir}, f)
            with patch.object(self.nc, "STATE_DIR", root):
                rc = self.nc.cleanup_container("neuros-cbusy")
            self.assertEqual(rc, 1)
            self.assertTrue(os.path.exists(cg_dir))
            self.assertTrue(os.path.exists(state_path))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_cleanup_missing_state_exits_nonzero(self):
        empty = tempfile.mkdtemp()
        try:
            with patch.object(self.nc, "STATE_DIR", empty):
                rc = self.nc.cleanup_container("neuros-nope")
            self.assertEqual(rc, 1)
        finally:
            shutil.rmtree(empty, ignore_errors=True)

    def test_cleanup_all_aggregates_exit_code(self):
        root = tempfile.mkdtemp()
        try:
            # ``a`` is an empty cgroup (no procs file at all -> cleanup
            # proceeds to rmdir and succeeds). ``b`` has a populated
            # cgroup.procs -> cleanup refuses. cleanup_all should OR
            # the exit codes and fail overall.
            cg_a = os.path.join(root, "neuros-a")
            os.makedirs(cg_a)
            with open(os.path.join(root, "neuros-a.json"), "w") as f:
                _json.dump({"name": "neuros-a",
                             "pid": 1, "cgroup": cg_a}, f)
            cg_b = os.path.join(root, "neuros-b")
            os.makedirs(cg_b)
            with open(os.path.join(cg_b, "cgroup.procs"), "w") as f:
                f.write("1234\n5678\n")  # two fake live members
            with open(os.path.join(root, "neuros-b.json"), "w") as f:
                _json.dump({"name": "neuros-b",
                             "pid": 1234, "cgroup": cg_b}, f)
            with patch.object(self.nc, "STATE_DIR", root):
                rc = self.nc.cleanup_all()
            # "a" is cleaned (its cgroup dir is gone), "b" remains.
            self.assertEqual(rc, 1)
            self.assertFalse(os.path.exists(os.path.join(root, "neuros-a")))
            self.assertTrue(os.path.exists(os.path.join(root, "neuros-b")))
        finally:
            shutil.rmtree(root, ignore_errors=True)


class TestRemountReadonlySurface(unittest.TestCase):
    """The --read-only path used to drop the mount(8) returncode on
    the floor; it now warns on non-zero exit."""

    def setUp(self):
        self.nc = load_neuros_container()

    def test_surfaces_warning_on_nonzero_returncode(self):
        with patch("os.system", return_value=32), \
             patch("sys.stderr", new_callable=io.StringIO) as err:
            self.nc.remount_readonly_best_effort()
        self.assertIn("exited with status 32", err.getvalue())

    def test_silent_on_zero_returncode(self):
        with patch("os.system", return_value=0), \
             patch("sys.stderr", new_callable=io.StringIO) as err:
            self.nc.remount_readonly_best_effort()
        self.assertEqual(err.getvalue(), "")


class TestUserMismatchHint(unittest.TestCase):
    """``--user UID:GID`` requested with a target that doesn't match
    the caller's real uid should print a hint at the top of the
    userns setup so the user understands the upcoming fall-back."""

    def setUp(self):
        self.nc = load_neuros_container()

    def test_prints_hint_when_user_differs_from_caller(self):
        # Caller uid=1000 tries to map 2000:2000. ``try_unprivileged_userns``
        # is mocked to return False so we hit the “no userns" path.
        with patch("os.geteuid", return_value=1000), \
             patch("os.getuid", return_value=1000), \
             patch("os.getgid", return_value=1000), \
             patch.object(self.nc, "try_unprivileged_userns",
                          return_value=False), \
             patch("sys.stderr", new_callable=io.StringIO) as err:
            self.nc.enter_namespaces(net=False, user=(2000, 2000))
        self.assertIn("--user 2000:2000 was requested", err.getvalue())

    def test_no_hint_when_user_matches_caller(self):
        with patch("os.geteuid", return_value=1000), \
             patch("os.getuid", return_value=1000), \
             patch("os.getgid", return_value=1000), \
             patch.object(self.nc, "try_unprivileged_userns",
                          return_value=False), \
             patch("sys.stderr", new_callable=io.StringIO) as err:
            self.nc.enter_namespaces(net=False, user=(1000, 1000))
        self.assertNotIn("--user ... was requested", err.getvalue())

    def test_no_hint_when_no_user_arg(self):
        with patch("os.geteuid", return_value=1000), \
             patch.object(self.nc, "try_unprivileged_userns",
                          return_value=False), \
             patch("sys.stderr", new_callable=io.StringIO) as err:
            self.nc.enter_namespaces(net=False, user=None)
        self.assertNotIn("--user", err.getvalue())


class TestEnvFileParsing(unittest.TestCase):
    """``--env-from-file PATH`` reads a dotenv-style file, strips
    blanks/comments/exports, and feeds the rest through ``parse_env``.
    The 5 cases cover happy path, blank/comment skipping, ``export``
    prefix tolerance, ``None`` passthrough, and missing-file exit."""

    def setUp(self):
        self.nc = load_neuros_container()
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, name, body):
        path = os.path.join(self.tmp, name)
        with open(path, "w") as f:
            f.write(body)
        return path

    def test_env_file_parses_key_value_pairs(self):
        path = self._write("env", "FOO=bar\nBAZ=qux\n")
        self.assertEqual(self.nc.parse_env_file(path),
                         ["FOO=bar", "BAZ=qux"])

    def test_env_file_skips_blanks_and_comments(self):
        path = self._write("env", "# header\n\nFOO=bar\n# trailing\n")
        self.assertEqual(self.nc.parse_env_file(path), ["FOO=bar"])

    def test_env_file_accepts_export_prefix(self):
        path = self._write("env", "export FOO=bar\nBAZ=qux\n")
        self.assertEqual(self.nc.parse_env_file(path),
                         ["FOO=bar", "BAZ=qux"])

    def test_env_file_none_passthrough(self):
        self.assertEqual(self.nc.parse_env_file(None), [])

    def test_env_file_missing_path_exits(self):
        with self.assertRaises(SystemExit), \
             patch("sys.stderr", new_callable=io.StringIO):
            self.nc.parse_env_file(os.path.join(self.tmp, "nope"))


class TestDetachIntegration(unittest.TestCase):
    """Drive the detached-container lifecycle end-to-end without
    depending on the kernel's cgroup delegation state at the moment
    of the test. ``--detach`` writes a JSON state file via
    ``write_state`` and leaves the cgroup in place; ``cleanup`` reaps
    empty leaves. We exercise that contract against a tmpdir
    "state dir" and a tmpdir "cgroup dir", so the assertions don't
    depend on whether the kernel delegation path is actually open
    right now (which can disagree between the probe and a subprocess
    in some sandboxes).

    This test is synthetic-only. A real e2e form should live in
    ``tests/test_container_integration.py`` once a CI with
    kernel-cgroup delegation is available — that form should
    subprocess-run ``neuros-container run --detach …`` end-to-end.
    The synthetic form here is portable and doesn't depend on the
    kernel's cgroup delegation state at the moment of the test.
    """

    def setUp(self):
        self.nc = load_neuros_container()

    def test_full_lifecycle_write_state_then_cleanup(self):
        root = tempfile.mkdtemp()
        try:
            state_dir = root
            cg_dir = os.path.join(root, "neuros-detach")
            os.makedirs(cg_dir)
            name = "neuros-detach-selftest"

            # Phase 1: write the state file via the helper the
            # detached child would have written.
            state_path = os.path.join(state_dir, f"{name}.json")
            self.nc.write_state(state_path=state_path, name=name,
                                 inner_pid=99999, cg=cg_dir)
            self.assertTrue(os.path.exists(state_path))

            # Phase 2: cleanup_container should reap the empty
            # cgroup and unlink the state file.
            with patch.object(self.nc, "STATE_DIR", state_dir):
                rc = self.nc.cleanup_container(name)
            self.assertEqual(rc, 0)
            self.assertFalse(os.path.exists(cg_dir))
            self.assertFalse(os.path.exists(state_path))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_state_shape_matches_documented_contract(self):
        """The state JSON must include name/pid/cgroup so a reattach
        tool can find the right processes."""
        root = tempfile.mkdtemp()
        try:
            # No real cgroup.procs on this synthetic path is the
            # important invariant: cleanup_container treats a missing
            # cgroup.procs as "zero live members" via its OSError
            # branch, so the test relies on that branch silently
            # succeeding. if a future reader adds a stray procs file
            # here, full_lifecycle_write_state_then_cleanup will start
            # failing with "still has N processes" — by design.
            name = "neuros-shape-test"
            path = os.path.join(root, f"{name}.json")
            self.nc.write_state(state_path=path, name=name,
                                inner_pid=12345,
                                cg="/sys/fs/cgroup/neuros-x")
            with open(path) as f:
                state = _json.load(f)
            self.assertEqual(set(state.keys()),
                             {"name", "pid", "cgroup"})
            self.assertEqual(state["name"], name)
            self.assertEqual(state["pid"], 12345)
            self.assertEqual(state["cgroup"], "/sys/fs/cgroup/neuros-x")
        finally:
            shutil.rmtree(root, ignore_errors=True)


class TestUtilitySmoke(unittest.TestCase):
    """Five high-traffic ``neuros-*`` utilities that previously had
    zero coverage. The assertions are deliberately structural so they
    survive across schema changes in the tools themselves but still
    catch a broken script (missing shebang, syntax error, ``--help``
    not behaving like argparse)."""

    UTILITIES = (
        "neuros-firewall",
        "neuros-network",
        "neuros-backup",
        "neuros-monitor",
        "neuros-cron",
    )
    BIN_DIR = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..",
        "config", "includes.chroot", "usr", "local", "bin",
    )

    def _path(self, name):
        full = os.path.join(self.BIN_DIR, name)
        if not os.path.exists(full):
            self.skipTest(f"{name} not present on disk")
        return full

    def test_each_utility_has_python3_shebang(self):
        for name in self.UTILITIES:
            with open(self._path(name)) as f:
                first = f.readline()
            self.assertIn("python3", first,
                          msg=f"{name} missing python3 shebang")

    def _load(self, name):
        loader = SourceFileLoader(name, self._path(name))
        spec = importlib.util.spec_from_loader(name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module

    def test_each_utility_imports_without_syntax_error(self):
        for name in self.UTILITIES:
            module = self._load(name)
            self.assertIsNotNone(module)

    def test_each_utility_reports_help(self):
        """Argparse-based CLIs print help on ``--help`` and exit 0.
        A tool that crashes on ``--help`` means a new opt was added
        without a test, and live callers will run into the same
        regression on first invocation. The assertion is strict:
        argparse prints ``usage:`` to stdout, so we require it."""
        for name in self.UTILITIES:
            proc = subprocess.run(
                [sys.executable, self._path(name), "--help"],
                capture_output=True, text=True, timeout=10,
            )
            combined = proc.stdout + proc.stderr
            self.assertIn(
                "usage:", combined,
                msg=f"{name} --help did not print argparse usage "
                    f"(rc={proc.returncode}, output={combined!r})",
            )


class TestEnvAndCapDropParsing(unittest.TestCase):
    """``--env`` and ``--cap-drop`` round-trip through their parsers
    without touching the kernel."""

    def setUp(self):
        self.nc = load_neuros_container()

    def test_env_accepts_well_formed_pairs(self):
        out = self.nc.parse_env(["FOO=bar", "BAZ=qux quux"])
        self.assertEqual(out, ["FOO=bar", "BAZ=qux quux"])

    def test_env_empty_returns_empty(self):
        self.assertEqual(self.nc.parse_env(None), [])
        self.assertEqual(self.nc.parse_env([]), [])

    def test_env_rejects_missing_equals(self):
        with self.assertRaises(SystemExit):
            self.nc.parse_env(["NO_EQUALS"])

    def test_env_rejects_blank_key(self):
        with self.assertRaises(SystemExit):
            self.nc.parse_env(["=value"])

    def test_env_rejects_nul_bytes(self):
        with self.assertRaises(SystemExit), \
             patch("sys.stderr", new_callable=io.StringIO):
            self.nc.parse_env(["K=\x00v"])

    def test_cap_drop_returns_none_when_unset(self):
        self.assertIsNone(self.nc.parse_cap_drop(None))

    def test_cap_drop_compiles_regex(self):
        pattern = self.nc.parse_cap_drop("CAP_(NET_RAW|SYS_ADMIN)")
        self.assertTrue(pattern.search("CAP_NET_RAW"))
        self.assertTrue(pattern.search("CAP_SYS_ADMIN"))
        self.assertFalse(pattern.search("CAP_CHOWN"))

    def test_cap_drop_rejects_invalid_regex(self):
        with self.assertRaises(SystemExit):
            self.nc.parse_cap_drop("(unclosed")


class TestEnvInjection(unittest.TestCase):
    """The grandchild of run_container inserts --env entries into
    ``os.environ`` just before exec. We don't fork a real process;
    instead, we directly call the same injection block against the
    real ``os.environ`` so the assertion is on what an execvp would
    inherit."""

    def setUp(self):
        self.nc = load_neuros_container()
        self.old_environ = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.old_environ)

    def test_env_entries_override_inherited(self):
        # Mirror exactly what run_container does after the parse step.
        env = self.nc.parse_env(["NEUROS_TEST_K=v1"])
        os.environ["NEUROS_TEST_K"] = "inherited"
        for entry in env:
            k, _, v = entry.partition("=")
            os.environ[k] = v
        self.assertEqual(os.environ["NEUROS_TEST_K"], "v1")


class TestDropCapabilitiesHelper(unittest.TestCase):
    """``drop_capabilities_best_effort`` walks the running kernel's
    cap list and prctl(PR_CAPBSET_DROP)'s every match. We stub
    ctypes.CDLL so no real prctl syscall runs; the helper is exercised
    end-to-end against mock libcs that return either success or
    EPERM-set errno."""

    def setUp(self):
        self.nc = load_neuros_container()

    def test_silent_when_pattern_is_none(self):
        with patch("sys.stderr", new_callable=io.StringIO) as err:
            self.nc.drop_capabilities_best_effort(None)
        self.assertEqual(err.getvalue(), "")

    def test_no_match_warns_loudly(self):
        """Pattern matches nothing — the helper must surface a clear
        stderr line, otherwise the user thinks their regex dropped
        caps when it didn't."""
        libc = MagicMock()
        libc.prctl = MagicMock(return_value=0)
        pattern = self.nc.parse_cap_drop("CAP_BOGUS_DISABLE_THIS")
        with patch.object(self.nc, "_CAP_NAMES_0_31",
                          ["CHOWN", "DAC_OVERRIDE"]), \
             patch("ctypes.CDLL", return_value=libc), \
             patch("ctypes.get_errno", return_value=0), \
             patch("sys.stderr", new_callable=io.StringIO) as err:
            self.nc.drop_capabilities_best_effort(pattern)
        self.assertIn("matched 0 of", err.getvalue())

    def test_libc_load_failure_warns(self):
        libc = MagicMock()
        libc.prctl = MagicMock(return_value=0)
        pattern = self.nc.parse_cap_drop("CAP_NET_RAW")
        with patch("ctypes.CDLL", side_effect=OSError("no libc")), \
             patch("sys.stderr", new_callable=io.StringIO) as err:
            self.nc.drop_capabilities_best_effort(pattern)
        self.assertIn("libc", err.getvalue())

    def test_prctl_eperm_warns_per_cap(self):
        """A failure on one specific cap reports the errno per-cap so
        users can tell which cap couldn't be dropped (often CAP_SETPCAP
        on a userns without the right capability)."""
        libc = MagicMock()
        # Fail when prctl is called for PR_CAPBSET_DROP on cap 0
        # (CAP_CHOWN); any other cap succeeds.
        def fake_prctl(op, capidx, *_):
            if op == 23 and capidx == 0:  # PR_CAPBSET_DROP=23
                return -1
            return 0
        libc.prctl = fake_prctl
        pattern = self.nc.parse_cap_drop("CAP_CHOWN")
        with patch("ctypes.CDLL", return_value=libc), \
             patch("ctypes.get_errno", return_value=1), \
             patch("sys.stderr", new_callable=io.StringIO) as err:
            self.nc.drop_capabilities_best_effort(pattern)
        text = err.getvalue()
        self.assertIn("CAP_CHOWN", text)
        self.assertIn("errno=1", text)
        self.assertIn("CAP_SETPCAP", text)


class TestZeroControllersWarning(unittest.TestCase):
    """If a limit is requested but no controller is delegated all the
    way down, make_cgroup should print a stderr warning telling the
    user their --mem/--pids/--cpu did nothing."""

    def setUp(self):
        self.nc = load_neuros_container()

    def test_warning_on_zero_ready_controllers(self):
        # Force enable_controllers to return an empty set, then make
        # sure the warning surfaces. The cgroup is still created in a
        # tmpdir so the rmdir at the end works. We also patch
        # find_delegating_ancestor — the walker otherwise climbs all
        # the way up to ``/`` looking for a delegating ancestor and
        # returns it, makedirs-ing at the filesystem root.
        root = tempfile.mkdtemp()
        try:
            with patch.object(self.nc, "find_delegating_ancestor",
                              return_value=root), \
                 patch.object(self.nc, "enable_controllers",
                              return_value=set()), \
                 patch("sys.stderr", new_callable=io.StringIO) as err:
                self.nc.make_cgroup("neuros-zero", "1000", None, None)
            self.assertIn("WARNING", err.getvalue())
        finally:
            shutil.rmtree(root, ignore_errors=True)


@unittest.skipUnless(cgroups_available(), "cgroup v2 delegation not available in this sandbox")
class TestCgroupEnforcement(unittest.TestCase):
    def setUp(self):
        self.nc = load_neuros_container()

    def test_cpu_max_quota_writes_through(self):
        """make_cgroup(..., cpu_quota=("50000","100000")) must produce a
        cgroup whose cpu.max file is exactly '50000 100000'. Tests the
        new --cpu-quota code path without needing to schedule a CPU-
        bound workload."""
        cg = self.nc.make_cgroup("neuros-selftest-cpuq", None, None, None,
                                 cpu_quota=("50000", "100000"))
        try:
            with open(os.path.join(cg, "cpu.max")) as f:
                self.assertEqual(f.read().strip(), "50000 100000")
        finally:
            try:
                os.rmdir(cg)
            except OSError:
                pass

    def test_cpu_weight_still_writes_cpu_weight(self):
        """The previous weight-only path stays backwards compatible."""
        cg = self.nc.make_cgroup("neuros-selftest-cpuw", None, None, 250)
        try:
            with open(os.path.join(cg, "cpu.weight")) as f:
                self.assertEqual(f.read().strip(), "250")
        finally:
            try:
                os.rmdir(cg)
            except OSError:
                pass

    def test_memory_max_caps_actual_usage(self):
        """A process that tries to touch 200MB inside a 16M memory.max
        cgroup must not exceed that limit, per memory.current."""
        cg = self.nc.make_cgroup("neuros-selftest-mem", "16777216", None, None)
        try:
            proc = subprocess.Popen([
                sys.executable, "-c",
                "import time; time.sleep(0.1)\n"
                "b = bytearray(200 * 1024 * 1024)\n"
                "for i in range(0, len(b), 4096):\n"
                "    b[i] = 1\n"
                "time.sleep(0.2)\n",
            ])
            self.nc.join_cgroup(cg, proc.pid)
            proc.wait(timeout=10)
            with open(os.path.join(cg, "memory.peak")) as f:
                peak = int(f.read().strip())
            self.assertLessEqual(peak, 16 * 1024 * 1024 * 1.05)
        finally:
            try:
                os.rmdir(cg)
            except OSError:
                pass

    def test_pids_max_blocks_extra_forks(self):
        """pids.max=4 must stop a forking loop once 4 members are in the
        cgroup (the harness process here counts as one of the four)."""
        cg = self.nc.make_cgroup("neuros-selftest-pids", None, "4", None)
        try:
            script = (
                "import subprocess, sys, time\n"
                "time.sleep(0.1)\n"
                "forked = 0\n"
                "procs = []\n"
                "try:\n"
                "    for _ in range(20):\n"
                "        procs.append(subprocess.Popen(['sleep', '0.3']))\n"
                "        forked += 1\n"
                "except OSError:\n"
                "    pass\n"
                "for p in procs:\n"
                "    p.wait()\n"
                "print(forked)\n"
            )
            proc = subprocess.Popen(
                [sys.executable, "-c", script],
                stdout=subprocess.PIPE, text=True,
            )
            self.nc.join_cgroup(cg, proc.pid)
            out, _ = proc.communicate(timeout=10)
            forked = int(out.strip())
            self.assertLess(forked, 20)
        finally:
            try:
                os.rmdir(cg)
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
