#!/usr/bin/env python3
"""
test_neuroslib.py — Unit tests for the shared neuroslib module.

Covers section-aware config parsing (replacing the per-tool
key=value loops in nn and neuros-model), JSON DB atomic writes, and
the canonical helpers get_default_model/get_context_config/
set_default_model. Runs in a tempdir so it doesn't touch the user's
real ~/.config/neuros.
"""

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from unittest.mock import patch

LIB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..",
    "config", "includes.chroot", "usr", "local", "bin", "neuroslib.py",
)


def load_lib():
    loader = SourceFileLoader("neuroslib", LIB_PATH)
    spec = importlib.util.spec_from_loader("neuroslib", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class TestLoadConfig(unittest.TestCase):
    """The new configparser-backed loader must understand [section]
    headers, comments, and quote stripping that the prior naive loop
    couldn't handle cleanly."""

    def setUp(self):
        self.lib = load_lib()
        self.tmp = tempfile.mkdtemp()

    def test_returns_defaults_for_missing_file(self):
        cfg = self.lib.load_config(os.path.join(self.tmp, "missing.conf"))
        self.assertEqual(cfg["llm.model"], "mistral")
        self.assertEqual(cfg["llm.host"], "localhost")
        self.assertEqual(cfg["llm.port"], "11434")
        self.assertFalse(cfg["context.window_title"])
        self.assertFalse(cfg["context.clipboard"])
        self.assertFalse(cfg["context.recent_files"])

    def test_parses_flat_llm_section(self):
        path = os.path.join(self.tmp, "llm.conf")
        with open(path, "w") as f:
            f.write('[llm]\nmodel = "codellama"\nhost = example\nport = 9999\n')
        cfg = self.lib.load_config(path)
        self.assertEqual(cfg["llm.model"], "codellama")
        self.assertEqual(cfg["llm.host"], "example")
        self.assertEqual(cfg["llm.port"], "9999")

    def test_parses_context_section_with_truthy(self):
        path = os.path.join(self.tmp, "llm.conf")
        with open(path, "w") as f:
            f.write('[context]\nwindow_title = true\nclipboard = 1\nrecent_files = yes\n')
        cfg = self.lib.load_config(path)
        self.assertTrue(cfg["context.window_title"])
        self.assertTrue(cfg["context.clipboard"])
        self.assertTrue(cfg["context.recent_files"])

    def test_unknown_truthy_strings_default_off(self):
        path = os.path.join(self.tmp, "llm.conf")
        with open(path, "w") as f:
            f.write('[context]\nwindow_title = maybe\n')
        cfg = self.lib.load_config(path)
        self.assertFalse(cfg["context.window_title"])

    def test_full_line_comments_are_ignored(self):
        path = os.path.join(self.tmp, "llm.conf")
        with open(path, "w") as f:
            f.write('# this is a comment\n[llm]\n# another\nmodel = "mistral"\n')
        cfg = self.lib.load_config(path)
        self.assertEqual(cfg["llm.model"], "mistral")

    def test_interpolation_in_value_is_not_resolved(self):
        """Model names with '=' in them (e.g. custom tags like
        'code=base') must round-trip verbatim, which configparser
        interpolation would otherwise mangle."""
        path = os.path.join(self.tmp, "llm.conf")
        with open(path, "w") as f:
            f.write('[llm]\nmodel = "custom=tag"\n')
        cfg = self.lib.load_config(path)
        self.assertEqual(cfg["llm.model"], "custom=tag")


class TestGetDefaultModel(unittest.TestCase):
    def setUp(self):
        self.lib = load_lib()
        self.tmp = tempfile.mkdtemp()

    def test_returns_fallback_on_missing_config(self):
        path = os.path.join(self.tmp, "nope.conf")
        self.assertEqual(self.lib.get_default_model(path), "mistral")

    def test_strips_quotes_in_value(self):
        path = os.path.join(self.tmp, "llm.conf")
        with open(path, "w") as f:
            f.write('[llm]\nmodel = "qwen2.5:7b"\n')
        self.assertEqual(self.lib.get_default_model(path), "qwen2.5:7b")

    def test_blank_model_falls_back(self):
        path = os.path.join(self.tmp, "llm.conf")
        with open(path, "w") as f:
            f.write('[llm]\nmodel = "   "\n')
        self.assertEqual(self.lib.get_default_model(path), "mistral")


class TestGetContextConfig(unittest.TestCase):
    def setUp(self):
        self.lib = load_lib()
        self.tmp = tempfile.mkdtemp()

    def test_all_off_when_file_missing(self):
        cfg = self.lib.get_context_config(os.path.join(self.tmp, "nope.conf"))
        self.assertEqual(cfg, {
            "window_title": False, "clipboard": False, "recent_files": False,
        })

    def test_only_explicit_sources_enabled(self):
        path = os.path.join(self.tmp, "llm.conf")
        with open(path, "w") as f:
            f.write('[context]\nwindow_title = true\n')
        cfg = self.lib.get_context_config(path)
        self.assertTrue(cfg["window_title"])
        self.assertFalse(cfg["clipboard"])
        self.assertFalse(cfg["recent_files"])


class TestSetDefaultModel(unittest.TestCase):
    def setUp(self):
        self.lib = load_lib()
        self.tmp = tempfile.mkdtemp()

    def test_creates_file_and_directory(self):
        path = os.path.join(self.tmp, "deep", "dir", "llm.conf")
        self.lib.set_default_model("llama3", path)
        self.assertTrue(os.path.exists(path))
        with open(path) as f:
            data = f.read()
        self.assertIn('model = llama3', data)

    def test_preserves_existing_keys(self):
        path = os.path.join(self.tmp, "llm.conf")
        with open(path, "w") as f:
            f.write('[llm]\nmodel = "mistral"\ncontext_window = 4096\n')
        self.lib.set_default_model("codellama", path)
        with open(path) as f:
            data = f.read()
        self.assertIn('model = codellama', data)
        self.assertIn('context_window = 4096', data)
        self.assertNotIn('mistral', data)

    def test_preserves_context_section(self):
        path = os.path.join(self.tmp, "llm.conf")
        with open(path, "w") as f:
            f.write('[llm]\nmodel = "mistral"\n[context]\nclipboard = true\n')
        self.lib.set_default_model("qwen", path)
        with open(path) as f:
            data = f.read()
        self.assertIn("[context]", data)
        self.assertIn("clipboard = true", data)
        self.assertIn('model = qwen', data)

    def test_overwrites_model_only(self):
        path = os.path.join(self.tmp, "llm.conf")
        with open(path, "w") as f:
            f.write('[llm]\nmodel = "old"\ncontext_window = 8192\n'
                    '[context]\nwindow_title = true\n')
        self.lib.set_default_model("new", path)
        with open(path) as f:
            data = f.read()
        # Host/port are NOT touched, so the configurable values survive.
        self.assertIn("context_window = 8192", data)
        self.assertIn("window_title = true", data)


class TestLoadDbSaveDb(unittest.TestCase):
    def setUp(self):
        self.lib = load_lib()
        self.tmp = tempfile.mkdtemp()

    def test_save_then_load_round_trips(self):
        path = os.path.join(self.tmp, "state.json")
        self.lib.save_db(path, {"a": 1, "b": [2, 3, 4]})
        self.assertEqual(self.lib.load_db(path), {"a": 1, "b": [2, 3, 4]})

    def test_load_db_returns_default_when_missing(self):
        self.assertEqual(
            self.lib.load_db(os.path.join(self.tmp, "nope.json"),
                             default={"x": 9}),
            {"x": 9},
        )

    def test_save_db_writes_pretty_indented_json(self):
        path = os.path.join(self.tmp, "pretty.json")
        self.lib.save_db(path, {"k": "v"})
        with open(path) as f:
            text = f.read()
        self.assertIn("\n  ", text)  # two-space indent present
        j = json.loads(text)
        self.assertEqual(j, {"k": "v"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
