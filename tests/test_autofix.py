#!/usr/bin/env python3
"""
test_autofix.py — Unit tests for neuros-autofix
Tests all 8 check modules and all 10+ fix modules using mocked system commands.
"""

import sys
import os
import json
import unittest
from unittest.mock import patch, MagicMock, mock_open
from io import StringIO

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                   "config", "includes.chroot", "usr", "local", "bin"))

import importlib.util
from importlib.machinery import SourceFileLoader

def load_module(name, path):
    # neuros-* scripts have no .py extension, so spec_from_file_location can't
    # infer a loader on its own (it returns None) -- pass one explicitly.
    loader = SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module

autofix_path = os.path.join(os.path.dirname(__file__), "..",
    "config", "includes.chroot", "usr", "local", "bin", "neuros-autofix")
autofix = load_module("neuros_autofix", autofix_path)


class TestCheckModules(unittest.TestCase):
    """Test all diagnostic check modules."""

    @patch.object(autofix, 'run_cmd')
    def test_check_services_all_ok(self, mock_run):
        mock_run.return_value = ("", "", 0)
        issues = autofix.check_services()
        self.assertEqual(issues, [])

    @patch.object(autofix, 'run_cmd')
    def test_check_services_down(self, mock_run):
        def side_effect(cmd_list, **kwargs):
            if "ollama" in str(cmd_list):
                return ("", "", 1)
            return ("", "", 0)
        mock_run.side_effect = side_effect
        issues = autofix.check_services()
        self.assertTrue(any(i["service"] == "ollama" for i in issues))

    @patch.object(autofix, 'run_cmd')
    def test_check_disk_full(self, mock_run):
        mock_run.return_value = ("Filesystem  Size  Used Avail Use% Mounted on\n/dev/sda1 100G 97G 3G 98% /", "", 0)
        issues = autofix.check_disk_space()
        self.assertTrue(any(i["type"] == "disk_full" for i in issues))

    @patch.object(autofix, 'run_cmd')
    def test_check_disk_low(self, mock_run):
        mock_run.return_value = ("Filesystem  Size  Used Avail Use% Mounted on\n/dev/sda1 100G 85G 15G 85% /", "", 0)
        issues = autofix.check_disk_space()
        self.assertTrue(any(i["type"] == "disk_low" for i in issues))

    @patch.object(autofix, 'run_cmd')
    def test_check_disk_ok(self, mock_run):
        mock_run.return_value = ("Filesystem  Size  Used Avail Use% Mounted on\n/dev/sda1 100G 50G 50G 50% /", "", 0)
        issues = autofix.check_disk_space()
        self.assertEqual(issues, [])

    @patch.object(autofix, 'run_cmd')
    def test_check_memory_high(self, mock_run):
        mock_run.return_value = (
            "              total        used        free\n"
            "Mem:          16000       15500         500\n"
            "Swap:          8000        7000        1000", "", 0)
        issues = autofix.check_memory()
        self.assertTrue(any(i["type"] == "memory_low" for i in issues))
        self.assertTrue(any(i["type"] == "swap_high" for i in issues))

    @patch.object(autofix, 'run_cmd')
    def test_check_memory_ok(self, mock_run):
        mock_run.return_value = (
            "              total        used        free\n"
            "Mem:          16000        4000       12000\n"
            "Swap:          8000         500        7500", "", 0)
        issues = autofix.check_memory()
        self.assertEqual(issues, [])

    @patch.object(autofix, 'run_cmd')
    def test_check_broken_packages(self, mock_run):
        mock_run.return_value = ("package-a: broken dependency\npackage-b: half-configured", "", 0)
        issues = autofix.check_broken_packages()
        self.assertEqual(len(issues), 2)
        self.assertTrue(all(i["type"] == "broken_package" for i in issues))

    @patch.object(autofix, 'run_cmd')
    def test_check_broken_packages_ok(self, mock_run):
        mock_run.return_value = ("", "", 0)
        issues = autofix.check_broken_packages()
        self.assertEqual(issues, [])

    @patch.object(autofix, 'run_cmd')
    def test_check_failed_services(self, mock_run):
        mock_run.return_value = ("cron.service loaded failed failed\nnginx.service loaded failed failed", "", 0)
        issues = autofix.check_failed_services()
        self.assertEqual(len(issues), 2)
        self.assertTrue(all(i["type"] == "failed_service" for i in issues))

    @patch.object(autofix, 'run_cmd')
    def test_check_failed_services_ok(self, mock_run):
        mock_run.return_value = ("", "", 0)
        issues = autofix.check_failed_services()
        self.assertEqual(issues, [])

    @patch('subprocess.run')
    def test_check_cron_errors(self, mock_run):
        mock_result = MagicMock()
        mock_result.stdout = "error: cron job failed for user root"
        mock_run.return_value = mock_result
        issues = autofix.check_cron_errors()
        self.assertTrue(len(issues) > 0)

    @patch('subprocess.run')
    def test_check_cron_no_errors(self, mock_run):
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_run.return_value = mock_result
        issues = autofix.check_cron_errors()
        self.assertEqual(issues, [])


class TestFixModules(unittest.TestCase):
    """Test all fix modules."""

    @patch.object(autofix, 'run_cmd')
    @patch.object(autofix, 'log_action')
    def test_fix_service_down(self, mock_log, mock_run):
        mock_run.return_value = ("", "", 0)
        result = autofix.fix_service_down({"service": "nginx", "severity": "high"})
        self.assertIn("Restarted nginx", result)

    @patch.object(autofix, 'run_cmd')
    @patch.object(autofix, 'log_action')
    def test_fix_service_down_failure(self, mock_log, mock_run):
        mock_run.return_value = ("", "permission denied", 1)
        result = autofix.fix_service_down({"service": "nginx", "severity": "high"})
        self.assertIn("Failed", result)

    @patch.object(autofix, 'run_cmd')
    @patch.object(autofix, 'log_action')
    def test_fix_disk_full(self, mock_log, mock_run):
        mock_run.return_value = ("", "", 0)
        result = autofix.fix_disk_full({"type": "disk_full", "severity": "critical"})
        self.assertIn("apt autoremove", result)
        self.assertIn("apt clean", result)
        self.assertIn("journal vacuum", result)

    @patch.object(autofix, 'run_cmd')
    @patch.object(autofix, 'log_action')
    def test_fix_disk_low(self, mock_log, mock_run):
        mock_run.return_value = ("", "", 0)
        result = autofix.fix_disk_low({"type": "disk_low", "severity": "medium"})
        self.assertIn("apt clean", result)
        self.assertIn("journal vacuum", result)
        self.assertNotIn("autoremove", result)

    @patch.object(autofix, 'run_cmd')
    @patch.object(autofix, 'log_action')
    def test_fix_broken_package(self, mock_log, mock_run):
        mock_run.return_value = ("", "", 0)
        result = autofix.fix_broken_package({"type": "broken_package", "severity": "high"})
        self.assertIn("dpkg --configure -a", result)

    @patch.object(autofix, 'run_cmd')
    @patch.object(autofix, 'log_action')
    def test_fix_failed_service(self, mock_log, mock_run):
        mock_run.side_effect = [("", "", 0), ("", "", 0)]
        result = autofix.fix_failed_service({"service": "cron", "severity": "high"})
        self.assertIn("Reset + restart cron", result)

    @patch.object(autofix, 'run_cmd')
    @patch.object(autofix, 'log_action')
    def test_fix_wrong_owner(self, mock_log, mock_run):
        mock_run.return_value = ("", "", 0)
        with patch.dict(os.environ, {"USER": "testuser"}):
            with patch.object(os.path, 'expanduser', return_value="/home/testuser"):
                result = autofix.fix_wrong_owner({"files": ["Documents"], "severity": "medium"})
                self.assertIn("Documents", result)

    @patch.object(autofix, 'run_cmd')
    @patch.object(autofix, 'log_action')
    def test_fix_memory_low(self, mock_log, mock_run):
        mock_run.side_effect = [("process1 10.5 8.2", "", 0), ("", "", 0)]
        result = autofix.fix_memory_low({"type": "memory_low", "severity": "high"})
        self.assertIn("Dropped page cache", result)

    @patch.object(autofix, 'run_cmd')
    @patch.object(autofix, 'log_action')
    def test_fix_swap_high(self, mock_log, mock_run):
        mock_run.side_effect = [("proc 1.0 0.5", "", 0), ("", "", 0), ("", "", 0), ("", "", 0)]
        result = autofix.fix_swap_high({"type": "swap_high", "severity": "medium"})
        self.assertIn("Swap cycled", result)

    @patch.object(autofix, 'run_cmd')
    @patch.object(autofix, 'log_action')
    def test_fix_swap_high_busy(self, mock_log, mock_run):
        mock_run.side_effect = [("proc 1.0 0.5", "", 0), ("", "", 0),
                                 ("", "Cannot allocate memory", 1)]
        result = autofix.fix_swap_high({"type": "swap_high", "severity": "medium"})
        self.assertIn("swapoff skipped", result)


class TestRunFixes(unittest.TestCase):
    """Test the run_fixes orchestration."""

    @patch.object(autofix, 'check_sudo', return_value=True)
    @patch.object(autofix, 'run_cmd')
    @patch.object(autofix, 'log_action')
    def test_run_fixes_dry_run(self, mock_log, mock_run, mock_sudo):
        issues = [{"type": "disk_full", "severity": "critical", "mount": "/"}]
        autofix.run_fixes(issues, dry_run=True)
        mock_run.assert_not_called()

    @patch.object(autofix, 'check_sudo', return_value=True)
    @patch.object(autofix, 'run_cmd')
    @patch.object(autofix, 'log_action')
    def test_run_fixes_sorted_by_severity(self, mock_log, mock_run, mock_sudo):
        mock_run.return_value = ("", "", 0)
        issues = [
            {"type": "disk_low", "severity": "medium", "mount": "/"},
            {"type": "memory_low", "severity": "high", "used_pct": 95},
            {"type": "disk_full", "severity": "critical", "mount": "/"},
        ]
        autofix.run_fixes(issues)
        self.assertGreaterEqual(mock_run.call_count, 3)

    def test_run_fixes_empty(self):
        autofix.run_fixes([])


class TestRunCmd(unittest.TestCase):
    """Test the run_cmd helper."""

    def test_run_cmd_basic(self):
        out, err, rc = autofix.run_cmd(["echo", "hello"])
        self.assertEqual(rc, 0)
        self.assertEqual(out, "hello")

    def test_run_cmd_failure(self):
        out, err, rc = autofix.run_cmd(["nonexistent_command_xyz"])
        self.assertNotEqual(rc, 0)

    def test_run_cmd_timeout(self):
        out, err, rc = autofix.run_cmd(["sleep", "60"], timeout=1)
        self.assertEqual(rc, 124)


class TestCheckSudo(unittest.TestCase):
    """Test sudo detection."""

    @patch.object(autofix, 'run_cmd')
    def test_check_sudo_available(self, mock_run):
        mock_run.return_value = ("", "", 0)
        self.assertTrue(autofix.check_sudo())

    @patch.object(autofix, 'run_cmd')
    def test_check_sudo_unavailable(self, mock_run):
        mock_run.return_value = ("", "", 1)
        self.assertFalse(autofix.check_sudo())


class TestAIHelpers(unittest.TestCase):
    """Test AI diagnosis functions."""

    def test_ai_diagnose_no_issues(self):
        result = autofix.ai_diagnose([], {})
        self.assertIn("No issues", result)

    @patch.object(autofix, 'ollama_generate')
    def test_ai_diagnose_with_issues(self, mock_ollama):
        mock_ollama.return_value = "1. ROOT CAUSE: test\n2. ACTION PLAN: fix it\n3. RISK LEVEL: LOW"
        result = autofix.ai_diagnose(
            [{"type": "disk_full", "severity": "critical"}], {"hostname": "test"}
        )
        self.assertIn("ROOT CAUSE", result)

    @patch.object(autofix, 'ollama_generate', return_value=None)
    def test_ai_diagnose_ollama_unavailable(self, mock_ollama):
        result = autofix.ai_diagnose([{"type": "test"}], {})
        self.assertIn("unavailable", result)


class TestLogging(unittest.TestCase):
    """Test action logging."""

    def setUp(self):
        self.tmp_dir = "/tmp/neuros_test_autofix"
        autofix.LOG_DIR = self.tmp_dir
        autofix.LOG_FILE = os.path.join(self.tmp_dir, "history.json")
        os.makedirs(self.tmp_dir, exist_ok=True)
        if os.path.exists(autofix.LOG_FILE):
            os.unlink(autofix.LOG_FILE)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_log_action(self):
        autofix.log_action("test", "target", ["cmd", "arg"], "result", True)
        self.assertTrue(os.path.exists(autofix.LOG_FILE))
        with open(autofix.LOG_FILE) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["action"], "test")
        self.assertTrue(data[0]["success"])


class TestFormatSize(unittest.TestCase):
    """Test size formatting utility."""

    def test_bytes(self):
        self.assertEqual(autofix._format_size(500), "500.0 B")

    def test_kb(self):
        self.assertEqual(autofix._format_size(2048), "2.0 KB")

    def test_mb(self):
        self.assertEqual(autofix._format_size(1048576 * 5), "5.0 MB")

    def test_gb(self):
        self.assertEqual(autofix._format_size(1073741824 * 3), "3.0 GB")


if __name__ == "__main__":
    unittest.main(verbosity=2)
