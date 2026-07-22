"""Smoke-test every executable installed by the NeurOS tools hook."""

import ast
import os
import pathlib
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOLS = ROOT / "config" / "includes.chroot" / "usr" / "local" / "bin"
ENTRYPOINTS = sorted(
    path for path in TOOLS.iterdir()
    if path.is_file() and os.access(path, os.X_OK)
)


class UtilitySmokeTests(unittest.TestCase):
    def test_entrypoint_inventory_is_complete(self):
        self.assertEqual(len(ENTRYPOINTS), 80)

    def test_python_and_shell_sources_parse(self):
        for path in ENTRYPOINTS:
            with self.subTest(path=path.name):
                first_line = path.read_bytes().splitlines()[0]
                if b"python" in first_line:
                    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                elif b"sh" in first_line or b"bash" in first_line:
                    result = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                else:
                    self.fail(f"missing recognized shebang: {path.name}")

    def test_help_for_every_entrypoint(self):
        failures = []
        for path in ENTRYPOINTS:
            with self.subTest(path=path.name):
                result = subprocess.run(
                    [str(path), "--help"],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode != 0:
                    failures.append(f"{path.name}: rc={result.returncode}: {(result.stderr or result.stdout).strip()}")
        self.assertFalse(failures, "\n".join(failures))


if __name__ == "__main__":
    unittest.main()
