"""Check extension inheritance, route identity, encoding and collision failures."""

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
from wiremock_benchmark_cli.identity import mapping_id, owned_customer
from wiremock_benchmark_cli.plan import make_plans


ROOT = Path(__file__).resolve().parents[1]


class UriExtensionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "phase.yaml"
        self.raw = yaml.safe_load((ROOT / "wb.yaml").read_text())
        self.customer = self.raw["customers"]["2342342"]
        self.customer["uri_extension"] = "transactions"
        self.customer["ProductClasses"] = {
            "Inherited": None,
            "Override": {"uri_extension": "special/v1"},
            "Removed": {"uri_extension": ""},
        }

    def load(self):
        self.path.write_text(yaml.safe_dump(self.raw, sort_keys=False))
        return load_config(self.path)

    def plan(self):
        return make_plans(self.load(), mock="mock-5", customer="2342342", delay=1000)["targets"][0]

    def test_inherit_override_and_explicit_removal_before_product_suffix(self):
        plan = self.plan()
        self.assertEqual([m["request"]["urlPath"] for m in plan["mappings"]], [
            "/SecondCustomer/2342342/transactions/productClasses/Inherited",
            "/SecondCustomer/2342342/special/v1/productClasses/Override",
            "/SecondCustomer/2342342/productClasses/Removed",
        ])
        self.assertEqual([p["extension_source"] for p in plan["resolved_profiles"]], ["customer", "product", "product"])
        self.assertTrue(all(m["response"]["body"] == "" for m in plan["mappings"]))
        for url, mapping in zip(plan["request_urls"], plan["mappings"]):
            self.assertEqual(url, "http://localhost:19081/mock-5" + mapping["request"]["urlPath"])
        self.raw["wiremocks"]["mock-5"]["prefix_handling"] = "preserve"
        self.assertTrue(all(m["request"]["urlPath"].startswith("/mock-5/") for m in self.plan()["mappings"]))

    def test_shared_customer_routes_group_by_extension_and_have_distinct_owned_ids(self):
        self.customer["endpoint_scope"] = "customer"
        self.customer["ProductClasses"]["AlsoInherited"] = {"uri_extension": "transactions"}
        plan = self.plan()
        self.assertEqual(len(plan["mappings"]), 3)
        ids = {m["id"] for m in plan["mappings"]}
        self.assertEqual(len(ids), 3)
        self.assertTrue(all(owned_customer(m) == "2342342" for m in plan["mappings"]))
        self.assertEqual(plan["resolved_profiles"][0]["product_classes"], ["Inherited", "AlsoInherited"])
        self.assertEqual(plan["resolved_profiles"][0]["extension_source"], "mixed")
        self.assertEqual(plan["mappings"][2]["id"], mapping_id("2342342", None))
        before = copy.deepcopy(plan["mappings"][0])
        self.customer["ProductClasses"] = {"AnotherMember": None}
        self.assertEqual(self.plan()["mappings"][0], before)

    def test_extension_changes_update_product_ids_but_change_shared_customer_ids(self):
        before = self.plan()["mappings"][0]
        self.customer["uri_extension"] = "replacement"
        after = self.plan()["mappings"][0]
        self.assertEqual(before["id"], after["id"])
        self.assertEqual(before["metadata"], after["metadata"])
        self.assertNotEqual(before["request"], after["request"])
        self.customer["endpoint_scope"] = "customer"
        before = self.plan()["mappings"][0]
        self.customer["uri_extension"] = "new-root"
        after = self.plan()["mappings"][0]
        self.assertNotEqual(before["id"], after["id"])
        altered = copy.deepcopy(after)
        altered["metadata"]["wb"]["uriExtension"] = "forged"
        self.assertIsNone(owned_customer(altered))

    def test_omission_and_empty_customer_extension_have_same_routes(self):
        self.customer.pop("uri_extension")
        before = self.plan()
        self.customer["uri_extension"] = ""
        after = self.plan()
        self.assertEqual(before["mappings"], after["mappings"])
        self.assertEqual(before["resolved_profiles"][0]["extension_source"], "none")
        self.assertEqual(after["resolved_profiles"][0]["extension_source"], "customer")

    def test_each_path_segment_is_encoded(self):
        self.customer["uri_extension"] = "Some Path/Prödüct+C"
        self.assertIn("/Some%20Path/Pr%C3%B6d%C3%BCct+C/productClasses/", self.plan()["request_urls"][0])

    def test_invalid_extensions_fail_on_customers_and_products(self):
        original = copy.deepcopy(self.raw)
        for value in (None, 1, [], {}, "/leading", "trailing/", "double//slash", ".", "..", "a/../b", "a?x=1", "a#b", "%2F", "a\\b", " bad", "a/ bad", "a\nb", "a;b"):
            for where in ("customer", "product"):
                self.raw = copy.deepcopy(original)
                target = self.raw["customers"]["2342342"]
                if where == "product":
                    target = target["ProductClasses"]["Override"]
                target["uri_extension"] = value
                with self.subTest(value=value, where=where), self.assertRaises(ConfigError):
                    self.load()

    def test_cross_scope_route_collision_fails_before_http(self):
        self.customer["uri_extension"] = ""
        self.customer["ProductClasses"] = {
            "Normal": None,
            "Root": {"endpoint_scope": "customer", "uri_extension": "productClasses/Normal"},
        }
        self.load()
        with patch("wiremock_benchmark_cli.api.WireMockAdmin.request") as http, contextlib.redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(main(["--mock", "mock-5", "--customer", "2342342", "--delay", "1000", "-f", str(self.path)]), 2)
        self.assertIn("Conflicting endpoint scopes", errors.getvalue())
        http.assert_not_called()

    def test_list_shows_effective_extension_and_origin(self):
        self.load()
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["list", "-f", str(self.path), "--mock", "mock-5", "--customer", "2342342"]), 0)
        for expected in ('uri_extension="transactions" (customer)', 'uri_extension="special/v1" (product)', 'uri_extension="" (product)'):
            self.assertIn(expected, output.getvalue())

    def test_customer_path_replaces_name_and_code_before_extension_and_product(self):
        before = self.plan()
        self.customer["customer_path_override"] = "partner/orders"
        after = self.plan()
        self.assertEqual([m["request"]["urlPath"] for m in after["mappings"]], [
            "/partner/orders/transactions/productClasses/Inherited",
            "/partner/orders/special/v1/productClasses/Override",
            "/partner/orders/productClasses/Removed",
        ])
        self.assertEqual(before["wiremock_api"], after["wiremock_api"])
        for original, updated in zip(before["mappings"], after["mappings"]):
            self.assertEqual(original["id"], updated["id"])
            self.assertEqual(original["metadata"], updated["metadata"])
        self.customer["endpoint_scope"] = "customer"
        self.customer["ProductClasses"] = {"One": None}
        self.customer["uri_extension"] = ""
        self.assertEqual(self.plan()["request_urls"], ["http://localhost:19081/mock-5/partner/orders"])

    def test_customer_override_encoding_and_preserved_proxy_prefix(self):
        self.customer["customer_path_override"] = "Partner Name/Vérsion+1"
        self.raw["wiremocks"]["mock-5"]["prefix_handling"] = "preserve"
        mapping = self.plan()["mappings"][0]
        self.assertTrue(mapping["request"]["urlPath"].startswith("/mock-5/Partner%20Name/V%C3%A9rsion+1/transactions/"))

    def test_customer_overrides_cannot_collide_across_customers(self):
        for customer in self.raw["customers"].values():
            customer.update(customer_path_override="shared", endpoint_scope="customer", uri_extension="", ProductClasses={"One": None})
        self.load()
        with patch("wiremock_benchmark_cli.api.WireMockAdmin.request") as http, contextlib.redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(main(["--mock", "mock-5", "--all-customers", "--delay", "1000", "-f", str(self.path)]), 2)
        self.assertIn("Conflicting endpoint scopes or customers", errors.getvalue())
        http.assert_not_called()

    def test_invalid_customer_overrides_and_product_override_setting_fail(self):
        original = copy.deepcopy(self.raw)
        for value in (None, "", 1, [], "/leading", "trailing/", "double//slash", "..", "a/../b", "a?b", "a#b", "%2F", " a", "a\nb"):
            self.customer["customer_path_override"] = value
            with self.subTest(value=value), self.assertRaises(ConfigError):
                self.load()
        self.raw = original
        self.raw["customers"]["2342342"]["ProductClasses"]["Override"]["customer_path_override"] = "invalid-level"
        with self.assertRaises(ConfigError):
            self.load()


if __name__ == "__main__":
    unittest.main()
