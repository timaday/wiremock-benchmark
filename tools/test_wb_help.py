"""Check help is available without YAML dependencies and preserves CLI scope."""

import contextlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from wiremock_benchmark_cli.cli import main
from wiremock_benchmark_cli import __version__


ROOT = Path(__file__).resolve().parents[1]


class HelpTest(unittest.TestCase):
    def test_version_works_without_yaml_or_config_file(self):
        with tempfile.TemporaryDirectory() as directory:
            for command in ([], ["apply"], ["list"], ["verify"], ["clean"]):
                with self.subTest(command=command):
                    result = subprocess.run(
                        [sys.executable, "-S", str(ROOT / "wb"), *command, "--version"],
                        cwd=directory, capture_output=True, text=True, timeout=5)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.strip(), f"wiremock-benchmark-cli {__version__}")
                    self.assertEqual(result.stderr, "")

    def test_all_aliases_work_without_yaml_or_config_file(self):
        with tempfile.TemporaryDirectory() as directory:
            for command in ([], ["apply"], ["list"], ["verify"], ["clean"]):
                for flag in ("--help", "--h", "-h"):
                    with self.subTest(command=command, flag=flag):
                        result = subprocess.run(
                            [sys.executable, "-S", str(ROOT / "wb"), *command, flag],
                            cwd=directory, capture_output=True, text=True, timeout=5)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertIn("Examples:", result.stdout)
                        self.assertIn("-f CONFIG, --config CONFIG", result.stdout)
                        self.assertIn("-h, --h, --help", result.stdout)
                        if not command:
                            self.assertIn("Commands:", result.stdout)
                            self.assertIn("verify", result.stdout)
                        elif command == ["verify"]:
                            self.assertIn("default: 50ms", result.stdout)
                            self.assertIn("--max-overhead-ms", result.stdout)
                        elif command == ["list"]:
                            self.assertNotIn("--delay", result.stdout)

    def test_explicit_apply_uses_same_plan_as_default(self):
        args = ["-f", str(ROOT / "wb.yaml"), "--all-mocks", "--all-customers", "--delay", "1000", "--dry-run"]
        outputs = []
        with patch("wiremock_benchmark_cli.cli.apply_plans") as apply:
            for prefix in ([], ["apply"]):
                output = io.StringIO()
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(main([*prefix, *args]), 0)
                outputs.append(output.getvalue())
            apply.assert_not_called()
        self.assertEqual(*outputs)


if __name__ == "__main__":
    unittest.main()
