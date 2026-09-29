import unittest
import subprocess
import sys

from bench import call


class RunnerCommandTest(unittest.TestCase):
    def test_diagnostic_command_timeout_is_enforced(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            call([sys.executable, "-c", "import time; time.sleep(1)"], timeout=0.02)


if __name__ == "__main__":
    unittest.main()
