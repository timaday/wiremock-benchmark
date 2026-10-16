"""Check shared customer routes, overrides and explicit ambiguity failures."""

import contextlib
import copy
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

from wiremock_benchmark_cli.cli import main
from wiremock_benchmark_cli.config import ConfigError, load_config
from wiremock_benchmark_cli.plan import make_plans


ROOT = Path(__file__).resolve().parents[1]


class EndpointScopeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "wb.yaml"
        self.raw = yaml.safe_load((ROOT / "wb.yaml").read_text())
        self.customer = self.raw["customers"]["2342342"]
        self.customer["endpoint_scope"] = "customer"
        self.customer["ProductClasses"] = {
            "First": None,
            "Shared": {"response_profile": "empty-ok", "endpoint_scope": "customer"},
            "Separate": {"endpoint_scope": "product-class", "response_profile": "accepted"},
        }

    def load(self):
        self.path.write_text(yaml.safe_dump(self.raw, sort_keys=False))
        return load_config(self.path)

    def plan(self):
        return make_plans(self.load(), mock="mock-5", customer="2342342", delay=1000)["targets"][0]

    def test_shared_route_and_explicit_product_override(self):
        plan = self.plan()
        self.assertEqual(len(plan["mappings"]), 2)
        shared, separate = plan["mappings"]
        self.assertEqual(shared["request"]["urlPath"], "/SecondCustomer/2342342")
        self.assertEqual(shared["response"]["body"], "")
        self.assertTrue(plan["request_urls"][0].endswith("/mock-5/SecondCustomer/2342342"))
        self.assertEqual(separate["request"]["urlPath"], "/SecondCustomer/2342342/productClasses/Separate")
        self.assertIn("jsonBody", separate["response"])
        self.assertEqual(plan["resolved_profiles"][0]["product_classes"], ["First", "Shared"])
        self.assertEqual(plan["resolved_profiles"][0]["source"], "mixed")
        self.assertEqual(plan["resolved_profiles"][0]["scope_source"], "mixed")

    def test_shared_id_and_ownership_do_not_depend_on_membership_or_order(self):
        before = self.plan()["mappings"][0]
        self.customer["ProductClasses"] = {"RenamedMember": None}
        after = self.plan()["mappings"][0]
        self.assertEqual(before, after)
        self.customer["ProductClasses"] = {"NewFirst": None, "RenamedMember": None}
        self.assertEqual(before, self.plan()["mappings"][0])

    def test_scope_only_override_inherits_profile_and_preserves_prefix(self):
        self.customer["endpoint_scope"] = "product-class"
        self.customer["ProductClasses"] = {"Root": {"endpoint_scope": "customer"}, "Product": None}
        self.raw["wiremocks"]["mock-5"]["prefix_handling"] = "preserve"
        plan = self.plan()
        self.assertEqual(plan["mappings"][0]["request"]["urlPath"], "/mock-5/SecondCustomer/2342342")
        self.assertTrue(all(m["response"]["body"] == "" for m in plan["mappings"]))
        self.assertEqual(plan["resolved_profiles"][0]["source"], "customer")

    def test_conflicting_shared_profiles_fail_all_commands_without_network(self):
        self.customer["ProductClasses"]["Shared"]["response_profile"] = "accepted"
        self.load()
        for args in (["--all-mocks", "--delay", "1000"], ["list"],
                     ["verify", "--delay", "1000"], ["--all-mocks", "--delay", "1000", "--error-profile", "server-error"]):
            with self.subTest(args=args), patch("wiremock_benchmark_cli.api.WireMockAdmin.request") as http:
                errors = io.StringIO()
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(errors):
                    self.assertEqual(main([*args, "-f", str(self.path), "--all-customers"]), 2)
                self.assertIn("Conflicting response profiles", errors.getvalue())
                http.assert_not_called()

    def test_list_reports_shared_route_once_with_all_products(self):
        self.load()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["list", "-f", str(self.path), "--customer", "2342342", "--mock", "mock-5"]), 0)
        self.assertIn("2 configured endpoint(s)", output.getvalue())
        self.assertIn("product=First,Shared", output.getvalue())
        self.assertIn("endpoint_scope=customer (mixed)", output.getvalue())

    def test_required_and_invalid_scope_fail_validation(self):
        original = copy.deepcopy(self.raw)
        for value in (None, "unknown", [], True):
            self.raw = copy.deepcopy(original)
            self.raw["customers"]["2342342"]["endpoint_scope"] = value
            with self.subTest(value=value), self.assertRaises(ConfigError):
                self.load()
        self.raw = copy.deepcopy(original)
        del self.raw["customers"]["2342342"]["endpoint_scope"]
        with self.assertRaises(ConfigError):
            self.load()
        self.raw = copy.deepcopy(original)
        self.raw["customers"]["2342342"]["ProductClasses"]["Shared"]["endpoint_scope"] = "unknown"
        with self.assertRaises(ConfigError):
            self.load()

    def test_customer_endpoint_without_products_has_shared_identity(self):
        self.customer["ProductClasses"] = {"PreviousMember": None}
        before = self.plan()["mappings"]
        self.customer.pop("ProductClasses")
        omitted = self.plan()
        self.assertEqual(omitted["mappings"], before)
        self.assertEqual(omitted["resolved_profiles"][0]["product_classes"], [])
        self.customer["ProductClasses"] = {}
        self.assertEqual(self.plan()["mappings"], before)

    def test_products_required_for_product_class_scope_and_null_always_invalid(self):
        for scope in ("customer", "product-class"):
            for value in (None, [], {}):
                self.customer["endpoint_scope"] = scope
                self.customer["ProductClasses"] = value
                if scope == "customer" and value == {}:
                    continue
                with self.subTest(scope=scope, value=value), self.assertRaises(ConfigError):
                    self.load()
        self.customer["endpoint_scope"] = "product-class"
        self.customer.pop("ProductClasses")
        with self.assertRaises(ConfigError):
            self.load()


if __name__ == "__main__":
    unittest.main()
