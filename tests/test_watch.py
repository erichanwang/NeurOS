#!/usr/bin/env python3
"""
test_watch.py — Regression tests for neuros-watch command injection.

lint_file() builds a shell command by interpolating the watched file's path
directly into an f-string, then runs it with shell=True. Any file whose name
contains shell metacharacters (;, `, $(), quotes) executes as part of that
command. These tests use adversarial filenames to prove/guard against that.
"""

import sys
import os
import unittest
import importlib.util
from importlib.machinery import SourceFileLoader

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                   "config", "includes.chroot", "usr", "local", "bin"))


def load_module(name, path):
    loader = SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


watch_path = os.path.join(os.path.dirname(__file__), "..",
    "config", "includes.chroot", "usr", "local", "bin", "neuros-watch")
watch = load_module("neuros_watch", watch_path)

MARKER = "/tmp/neuros_watch_injection_test_marker"


class TestLintFileInjection(unittest.TestCase):
    """Adversarial filenames must not escape into the shell."""

    def setUp(self):
        if os.path.exists(MARKER):
            os.remove(MARKER)

    def tearDown(self):
        if os.path.exists(MARKER):
            os.remove(MARKER)

    def _watcher(self):
        return watch.FileWatcher(".", "lint")

    def test_semicolon_injection(self):
        payload = f"safe.py; touch {MARKER}; echo done.py"
        self._watcher().lint_file(payload)
        self.assertFalse(os.path.exists(MARKER),
            "semicolon in filename executed as a second shell command")

    def test_command_substitution_injection(self):
        payload = f"safe$(touch {MARKER}).py"
        self._watcher().lint_file(payload)
        self.assertFalse(os.path.exists(MARKER),
            "$() in filename executed as command substitution")

    def test_backtick_injection(self):
        payload = f"safe`touch {MARKER}`.py"
        self._watcher().lint_file(payload)
        self.assertFalse(os.path.exists(MARKER),
            "backticks in filename executed as command substitution")

    def test_newline_injection(self):
        payload = f"safe.py\ntouch {MARKER}\necho done.py"
        self._watcher().lint_file(payload)
        self.assertFalse(os.path.exists(MARKER),
            "embedded newline in filename executed as a second command")

    def test_leading_dash_not_treated_as_flag(self):
        # Not an injection, but a real file named "-rf" should still just be
        # passed through as a compile target, not swallowed as an option.
        result = self._watcher().lint_file("--help.py")
        # Should not raise; nothing to assert on stdout since py_compile
        # will just report the (nonexistent) file as missing.

    def test_space_in_filename_still_lints(self):
        # Plain spaces (no metacharacters) should not break argument
        # boundaries either.
        result = self._watcher().lint_file("my file.py")

    def test_quotes_in_filename_still_do_not_escape(self):
        for quote in ('"', "'"):
            self._watcher().lint_file(f"safe{quote}quoted.py")
        self.assertFalse(os.path.exists(MARKER))


if __name__ == "__main__":
    unittest.main(verbosity=2)
