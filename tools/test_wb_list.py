"""Exercise read-only listing, selectors and agreement with mapping generation."""

import contextlib
import copy
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml

from wiremock_benchmark_cli.cli import main
from wiremock_benchmark_cli.config import load_config
from wiremock_benchmark_cli.plan import make_plans


ROOT = Path(__file__).resolve().parents[1]


class ListEndpointsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "wb.yaml"
        self.config = yaml.safe_load((ROOT / "wb.yaml").read_text())

        self.config["customers"]["3243423434"]["name"] = "Test Customer"
        self.config["customers"]["2342342"]["name"] = "Second Customer"

    def run_list(self, *args):
        self.path.write_text(yaml.safe_dump(self.config, sort_keys=False))
        original = self.path.read_bytes()
        output, errors = io.StringIO(), io.StringIO()
        with patch("wiremock_benchmark_cli.cli.apply_plans") as apply, patch("wiremock_benchmark_cli.api.WireMockAdmin.request") as http:
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                result = main(["list", "--config", str(self.path), *args])
            apply.assert_not_called()
            http.assert_not_called()
        self.assertEqual(self.path.read_bytes(), original)
        return result, output.getvalue(), errors.getvalue()

    def test_one_customer_lists_all_five_mocks_without_network(self):
        status, output, errors = self.run_list("--customer", "2342342")
        self.assertEqual(status, 0, errors)
        self.assertIn("10 configured endpoint(s).", output)
        self.assertIn("live state not checked", output)
        self.assertNotIn("3243423434", output)
        for number in range(1, 6):
            self.assertIn(f"[mock-{number}] POST http://localhost:19081/mock-{number}/Second%20Customer/2342342/", output)
        self.assertIn("profile=empty-ok (customer)", output)
        self.assertIn("profile=accepted (product)", output)

    def test_all_customers_and_mock_filter(self):
        status, output, errors = self.run_list("--all-customers")
        self.assertEqual(status, 0, errors)
        self.assertIn("15 configured endpoint(s).", output)
        for code in self.config["customers"]:
            self.assertIn(f"Customer {code}:", output)
        status, output, errors = self.run_list("--all-customers", "--mock", "mock-2")
        self.assertEqual(status, 0, errors)
        self.assertIn("3 configured endpoint(s).", output)
        self.assertIn("[mock-2]", output)
        self.assertNotIn("[mock-1]", output)

    def test_urls_profiles_and_mapping_paths_match_apply_plan(self):
        self.config["wiremocks"]["mock-2"].update(api="http://localhost:19002", prefix_handling="preserve")
        self.config["customers"]["2342342"]["ProductClasses"]["C++"] = None
        status, output, errors = self.run_list("--all-customers", "--all-mocks")
        self.assertEqual(status, 0, errors)
        plan = make_plans(load_config(self.path), all_mocks=True, all_customers=True, delay=1000)
        for target in plan["targets"]:
            for url, mapping, resolution in zip(target["request_urls"], target["mappings"], target["resolved_profiles"]):
                self.assertIn(f"[{target['mock']}] POST {url}", output)
                self.assertIn(f"mapping_path={mapping['request']['urlPath']}", output)
                self.assertIn(f"profile={resolution['response_profile']} ({resolution['source']})", output)

    def test_unassigned_customer_and_filtered_empty_result_are_explicit(self):
        self.config["customers"]["unassigned"] = copy.deepcopy(self.config["customers"]["2342342"])
        status, output, errors = self.run_list("--all-customers")
        self.assertEqual(status, 0, errors)
        self.assertIn("Customer unassigned:", output)
        self.assertIn("No configured endpoints in the selected mocks.", output)
        self.assertIn("15 configured endpoint(s).", output)
        self.config["wiremocks"]["mock-1"]["customers"] = {"3243423434": {}}
        status, output, errors = self.run_list("--customer", "2342342", "--mock", "mock-1")
        self.assertEqual(status, 0, errors)
        self.assertIn("No configured endpoints", output)
        self.assertIn("0 configured endpoint(s).", output)
        self.assertNotIn("POST", output)

    def test_unknown_names_and_invalid_configuration_fail(self):
        for args in (("--customer", "missing"), ("--all-customers", "--mock", "missing")):
            with self.subTest(args=args):
                status, output, errors = self.run_list(*args)
                self.assertEqual(status, 2)
                self.assertEqual(output, "")
                self.assertIn("Unknown", errors)
        self.config["customers"]["2342342"]["response_profile"] = "missing"
        status, output, errors = self.run_list("--all-customers")
        self.assertEqual(status, 2)
        self.assertIn("unknown response profile", errors)

    def test_required_selector_and_apply_only_flags_are_rejected(self):
        for args in ([], ["--customer"], ["--customer", "2342342", "--all-customers"],
                     ["--all-customers", "--delay", "0"], ["--all-customers", "--error-profile", "timeout"],
                     ["--all-customers", "--wiremock-api", "http://host:8080"]):
            with self.subTest(args=args), self.assertRaises(SystemExit) as result:
                self.run_list(*args)
            self.assertEqual(result.exception.code, 2)

    def test_executable_list_command(self):
        result = subprocess.run([str(ROOT / "wb"), "list", "--config", str(ROOT / "wb.yaml"),
                                 "--customer", "2342342", "--mock", "mock-1"],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("2 configured endpoint(s).", result.stdout)
        self.assertIn("POST http://localhost:19081/mock-1/", result.stdout)


if __name__ == "__main__":
    unittest.main()
