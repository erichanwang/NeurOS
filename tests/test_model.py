#!/usr/bin/env python3
"""
test_model.py — Unit tests for neuros-model (the model-switcher CLI).
Tests config read/write and formatting logic without requiring Ollama.
"""

import os
import tempfile
import unittest
import importlib.util
from importlib.machinery import SourceFileLoader
from unittest.mock import patch

MODEL_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..",
    "config", "includes.chroot", "usr", "local", "bin", "neuros-model"
)


def load_neuros_model():
    loader = SourceFileLoader("neuros_model", MODEL_PATH)
    spec = importlib.util.spec_from_loader("neuros_model", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class TestFormatSize(unittest.TestCase):
    def setUp(self):
        self.m = load_neuros_model()

    def test_bytes(self):
        self.assertEqual(self.m.format_size(500), "500.0 B")

    def test_gb(self):
        self.assertEqual(self.m.format_size(4 * 1024 ** 3), "4.0 GB")


class TestConfigRoundTrip(unittest.TestCase):
    """Verify switch_model() writes a config that get_current_model() reads back correctly."""

    def setUp(self):
        self.m = load_neuros_model()
        self.tmpdir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.tmpdir, "llm.conf")

    def test_switch_creates_config_when_missing(self):
        with patch.object(self.m, "CONFIG_PATH", self.config_path), \
             patch.object(self.m, "api_request", return_value=None):
            self.m.switch_model("llama3")
        with open(self.config_path) as f:
            content = f.read()
        self.assertIn('model = "llama3"', content)

    def test_switch_replaces_existing_model_line(self):
        with open(self.config_path, "w") as f:
            f.write('[llm]\nmodel = "mistral"\ncontext_window = 4096\n')
        with patch.object(self.m, "CONFIG_PATH", self.config_path), \
             patch.object(self.m, "api_request", return_value=None):
            self.m.switch_model("codellama")
        with open(self.config_path) as f:
            content = f.read()
        self.assertIn('model = "codellama"', content)
        self.assertNotIn("mistral", content)
        self.assertIn("context_window = 4096", content)

    def test_get_current_model_reads_config(self):
        with open(self.config_path, "w") as f:
            f.write('model = "qwen2.5:7b"\n')
        with patch.object(self.m, "CONFIG_PATH", self.config_path):
            self.assertEqual(self.m.get_current_model(), "qwen2.5:7b")

    def test_get_current_model_defaults_when_missing(self):
        with patch.object(self.m, "CONFIG_PATH", os.path.join(self.tmpdir, "nope.conf")):
            self.assertEqual(self.m.get_current_model(), "mistral")


class TestBenchmarkTimeout(unittest.TestCase):
    """CPU inference of even a 1B model can take well over 10s;
    api_request must accept a longer timeout for generate calls
    or `neuros-model benchmark` spuriously reports 'timed out'."""

    def setUp(self):
        self.m = load_neuros_model()

    def test_api_request_accepts_custom_timeout(self):
        import inspect
        params = inspect.signature(self.m.api_request).parameters
        self.assertIn("timeout", params)
        self.assertEqual(params["timeout"].default, 10)

    def test_benchmark_uses_longer_timeout_for_generate(self):
        with patch.object(self.m, "api_request", return_value=None) as mock_req:
            self.m.benchmark_model("qwen2.5:0.5b")
        _, kwargs = mock_req.call_args
        self.assertEqual(kwargs.get("timeout"), 300)

    def test_compare_uses_longer_timeout_for_generate(self):
        with patch.object(self.m, "api_request", return_value=None) as mock_req:
            self.m.compare_models(["qwen2.5:0.5b"])
        _, kwargs = mock_req.call_args
        self.assertEqual(kwargs.get("timeout"), 300)


if __name__ == "__main__":
    unittest.main()
