#!/usr/bin/env python3
"""
test_container.py — Unit and integration tests for neuros-container.

The integration tests exercise real cgroup v2 enforcement (they create,
populate, and tear down an actual cgroup on the machine running the
suite) but skip cleanly if cgroup v2 delegation isn't available, the
same way the rest of this repo skips checks that need a full host.
"""

import os
import subprocess
import sys
import unittest
import importlib.util
from importlib.machinery import SourceFileLoader

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
    try:
        nc = load_neuros_container()
        cg = nc.make_cgroup("neuros-selftest-probe", "16777216", None, None)
        os.rmdir(cg)
        return True
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


@unittest.skipUnless(cgroups_available(), "cgroup v2 delegation not available in this sandbox")
class TestCgroupEnforcement(unittest.TestCase):
    def setUp(self):
        self.nc = load_neuros_container()

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
