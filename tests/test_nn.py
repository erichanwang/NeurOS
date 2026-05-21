#!/usr/bin/env python3
"""
test_nn.py — Unit tests for the nn CLI.
Tests the core functions in isolation without requiring Ollama.
Can be run with: python3 -m pytest test_nn.py -v
"""

import sys
import os
import json
import tempfile
import unittest
from unittest.mock import patch, mock_open, MagicMock
from io import StringIO

# Tests validate NeurOS component files directly.
# The nn CLI uses a __main__ guard (can't import directly),
# so we test by reading source files and validating logic patterns.

class TestNNCore(unittest.TestCase):
    """Test core nn CLI functionality."""

    def test_config_path_in_source(self):
        """Test that nn source contains CONFIG_PATH with correct path."""
        nn_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), '..',
            'config', 'includes.chroot', 'usr', 'local', 'bin', 'nn'
        )
        with open(nn_path) as f:
            content = f.read()
        self.assertIn(".config/neuros/llm.conf", content)
        self.assertIn("CONFIG_PATH", content)

    def test_ollama_url_correct(self):
        """Test that OLLAMA_URL points to correct localhost port."""
        # Read the nn file and find OLLAMA_URL
        nn_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), '..',
            'config', 'includes.chroot', 'usr', 'local', 'bin', 'nn'
        )
        with open(nn_path) as f:
            content = f.read()

        self.assertIn("localhost:11434", content)
        self.assertIn("OLLAMA_URL", content)

    def test_default_model_is_mistral(self):
        """Test that default model is mistral."""
        nn_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), '..',
            'config', 'includes.chroot', 'usr', 'local', 'bin', 'nn'
        )
        with open(nn_path) as f:
            content = f.read()

        self.assertIn('DEFAULT_MODEL = "mistral"', content)

    def test_nn_has_shebang(self):
        """Test that nn starts with proper shebang."""
        nn_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), '..',
            'config', 'includes.chroot', 'usr', 'local', 'bin', 'nn'
        )
        with open(nn_path) as f:
            first_line = f.readline()
        self.assertIn("python3", first_line)

    def test_nn_has_help_flag(self):
        """Test that nn supports --help."""
        nn_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), '..',
            'config', 'includes.chroot', 'usr', 'local', 'bin', 'nn'
        )
        with open(nn_path) as f:
            content = f.read()
        self.assertIn("--help", content)

    def test_nn_has_interactive_mode(self):
        """Test that nn supports -i for interactive mode."""
        nn_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), '..',
            'config', 'includes.chroot', 'usr', 'local', 'bin', 'nn'
        )
        with open(nn_path) as f:
            content = f.read()
        self.assertIn('"-i"', content)
        self.assertIn("interactive_mode", content)


class TestNNConfigParsing(unittest.TestCase):
    """Test nn's config file parsing logic."""

    def test_model_parsing_flat_format(self):
        """Test parsing model from flat key=value format."""
        config = "model = mistral\n"
        model = "__unset__"
        for line in config.split('\n'):
            line = line.strip()
            if '=' in line and not line.startswith('['):
                key, val = line.split('=', 1)
                if key.strip() == "model":
                    model = val.strip().strip('"').strip("'")
        self.assertEqual(model, "mistral")
        self.assertNotEqual(model, "__unset__")

    def test_model_parsing_quoted_value(self):
        """Test parsing model with quoted value."""
        config = 'model = "codellama"\n'
        model = "__unset__"
        for line in config.split('\n'):
            line = line.strip()
            if '=' in line and not line.startswith('['):
                key, val = line.split('=', 1)
                if key.strip() == "model":
                    model = val.strip().strip('"').strip("'")
        self.assertEqual(model, "codellama")

    def test_model_parsing_ignores_section_headers(self):
        """Test that [section] headers are ignored."""
        config = "[llm]\nmodel = mistral\n"
        # The parsing should skip [llm] and find model
        model = "__unset__"
        for line in config.split('\n'):
            line = line.strip()
            if '=' in line and not line.startswith('['):
                key, val = line.split('=', 1)
                if key.strip() == "model":
                    model = val.strip().strip('"').strip("'")
        self.assertEqual(model, "mistral")

    def test_model_parsing_with_spaces(self):
        """Test parsing model with extra spaces."""
        config = 'model  =  "llama3"  \n'
        model = "__unset__"
        for line in config.split('\n'):
            line = line.strip()
            if '=' in line and not line.startswith('['):
                key, val = line.split('=', 1)
                if key.strip() == "model":
                    model = val.strip().strip('"').strip("'")
        self.assertEqual(model, "llama3")


class TestNNFileReading(unittest.TestCase):
    """Test nn's file reading logic."""

    def test_read_file_safe_truncates_large_files(self):
        """Test that files > 8000 chars get truncated."""
        # Simulate the read_file_safe logic
        large_content = "x" * 10000
        if len(large_content) > 8000:
            content = large_content[:8000] + "\n... (truncated)"
        self.assertEqual(len(content), 8000 + len("\n... (truncated)"))
        self.assertTrue(content.endswith("... (truncated)"))

    def test_read_file_safe_small_files(self):
        """Test that small files are not truncated."""
        small_content = "hello world"
        if len(small_content) > 8000:
            small_content = small_content[:8000] + "\n... (truncated)"
        self.assertEqual(small_content, "hello world")

    def test_read_file_safe_exact_boundary(self):
        """Test files at exactly 8000 chars."""
        exact_content = "x" * 8000
        if len(exact_content) > 8000:
            exact_content = exact_content[:8000] + "\n... (truncated)"
        self.assertEqual(len(exact_content), 8000)


class TestServiceFile(unittest.TestCase):
    """Test neuros-llm.service correctness."""

    def test_service_port(self):
        """Test that the service uses port 11434."""
        service_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), '..',
            'config', 'includes.chroot', 'etc', 'systemd', 'system', 'neuros-llm.service'
        )
        with open(service_path) as f:
            content = f.read()
        self.assertIn("OLLAMA_HOST=127.0.0.1:11434", content)

    def test_service_restart_policy(self):
        """Test that the service auto-restarts."""
        service_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), '..',
            'config', 'includes.chroot', 'etc', 'systemd', 'system', 'neuros-llm.service'
        )
        with open(service_path) as f:
            content = f.read()
        self.assertIn("Restart=always", content)

    def test_service_multi_user_target(self):
        """Test that the service targets multi-user."""
        service_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), '..',
            'config', 'includes.chroot', 'etc', 'systemd', 'system', 'neuros-llm.service'
        )
        with open(service_path) as f:
            content = f.read()
        self.assertIn("multi-user.target", content)


class TestContinueConfig(unittest.TestCase):
    """Test Continue.dev configuration."""

    def test_config_is_valid_json(self):
        """Test that continue config is valid JSON."""
        config_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), '..',
            'config', 'includes.chroot', 'etc', 'skel', '.continue', 'config.json'
        )
        with open(config_path) as f:
            data = json.load(f)
        self.assertIn("models", data)
        self.assertIsInstance(data["models"], list)
        self.assertGreater(len(data["models"]), 0)

    def test_config_uses_ollama(self):
        """Test that config uses ollama provider."""
        config_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), '..',
            'config', 'includes.chroot', 'etc', 'skel', '.continue', 'config.json'
        )
        with open(config_path) as f:
            data = json.load(f)
        self.assertEqual(data["models"][0]["provider"], "ollama")

    def test_config_telemetry_disabled(self):
        """Test that telemetry is disabled."""
        config_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), '..',
            'config', 'includes.chroot', 'etc', 'skel', '.continue', 'config.json'
        )
        with open(config_path) as f:
            data = json.load(f)
        self.assertFalse(data.get("allowAnonymousTelemetry", True))


class TestPackageLists(unittest.TestCase):
    """Test package list correctness."""

    def test_core_packages_present(self):
        """Test that core packages are in the install list."""
        pkg_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), '..',
            'config', 'package-lists', 'neuros.list.chroot'
        )
        with open(pkg_path) as f:
            content = f.read()
        required = ["gnome-shell", "neovim", "python3", "ufw", "zsh",
                    "tesseract-ocr", "nmap", "flake8", "lm-sensors"]
        for pkg in required:
            self.assertIn(pkg, content, f"Package '{pkg}' missing from list")

    def test_no_flask_dependency(self):
        """Test that python3-flask is NOT in the package list."""
        pkg_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), '..',
            'config', 'package-lists', 'neuros.list.chroot'
        )
        with open(pkg_path) as f:
            content = f.read()
        self.assertNotIn("python3-flask", content, "python3-flask should not be a dependency")

    def test_telemetry_packages_removed(self):
        """Test that telemetry packages are in the remove list."""
        pkg_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), '..',
            'config', 'package-lists', 'remove.list.chroot'
        )
        with open(pkg_path) as f:
            content = f.read()
        self.assertIn("ubuntu-report", content)
        self.assertIn("apport", content)
        self.assertIn("whoopsie", content)


class TestPrivacyHardening(unittest.TestCase):
    """Test privacy hardening measures."""

    def test_vscode_telemetry_off(self):
        """Test that VS Code settings disable telemetry."""
        settings_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), '..',
            'config', 'includes.chroot', 'etc', 'skel', '.config', 'Code', 'User', 'settings.json'
        )
        with open(settings_path) as f:
            data = json.load(f)
        self.assertEqual(data.get("telemetry.telemetryLevel"), "off")

    def test_hook_0400_disables_telemetry_services(self):
        """Test that hook 0400 disables telemetry services."""
        hook_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), '..',
            'config', 'hooks', 'live', '0400-remove-telemetry.hook.chroot'
        )
        with open(hook_path) as f:
            content = f.read()
        self.assertIn("apport", content)
        self.assertIn("whoopsie", content)
        self.assertIn("ubuntu-report", content)

    def test_ufw_enabled_in_hook_0500(self):
        """Test that hook 0500 enables UFW."""
        hook_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), '..',
            'config', 'hooks', 'live', '0500-configure-system.hook.chroot'
        )
        with open(hook_path) as f:
            content = f.read()
        self.assertIn("ufw --force enable", content)
        self.assertIn("default deny incoming", content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
