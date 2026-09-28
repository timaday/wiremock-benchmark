import unittest
import subprocess
import sys

from bench import call, client_threads
from fixtures import DELAYS


class InjectorBudgetTest(unittest.TestCase):
    def test_mixed_workload_has_capacity_for_its_slowest_response(self):
        offered = 1020
        cases = [{"delay": delay} for delay in DELAYS]
        # Each reusable client is paced separately. An average-delay budget
        # starves the configured arrival rate when that client selects 6s.
        interval = client_threads(cases, offered) / offered
        self.assertGreater(interval, max(DELAYS) / 1000)

    def test_diagnostic_command_timeout_is_enforced(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            call([sys.executable, "-c", "import time; time.sleep(1)"], timeout=0.02)


if __name__ == "__main__":
    unittest.main()
