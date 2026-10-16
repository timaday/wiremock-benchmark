"""Check configured public probe methods, payload bytes and HEAD expectations."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import yaml

from wiremock_benchmark_cli.cli import main
from wiremock_benchmark_cli.config import ConfigError, load_config
from wiremock_benchmark_cli.plan import make_plans
from wiremock_benchmark_cli.requests import probe_payload
from wiremock_benchmark_cli.verify import probe
from wiremock_benchmark_cli.verify_expectations import expected_criteria


ROOT = Path(__file__).resolve().parents[1]
CODE = "2342342"


class RequestProfileTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "profile.yaml"
        self.raw = yaml.safe_load((ROOT / "wb.yaml").read_text())
        self.raw["request_profiles"] = {
            "submit": {"method": "POST", "probe_body": {"type": "json", "value": {"correlationId": "check"}}},
            "read": {"method": "GET", "probe_body": {"type": "none"}},
            "text": {"method": "PUT", "probe_body": {"type": "text", "value": "café"}}}

    def load(self):
        self.path.write_text(yaml.safe_dump(self.raw))
        return load_config(self.path)

    def plan(self):
        return make_plans(self.load(), mock="mock-1", customer=CODE)["targets"][0]

    def test_optional_catalogue_and_selection_preserve_post_json_default(self):
        self.raw.pop("request_profiles")
        target = self.plan()
        self.assertTrue(all(m["request"]["method"] == "POST" for m in target["mappings"]))
        for resolved in target["resolved_profiles"]:
            self.assertEqual(resolved["request_profile"], "default")
            self.assertEqual(resolved["request_profile_source"], "default")
            self.assertEqual(resolved["probe_body"], {"type": "json", "value": {}})

    def test_customer_inheritance_product_override_and_explicit_default(self):
        customer = self.raw["customers"][CODE]
        customer["request_profile"] = "submit"
        customer["ProductClasses"] = {"Inherited": None, "Read": {"request_profile": "read"},
                                       "Reset": {"request_profile": "default"}}
        config = self.load()
        unchanged = copy.deepcopy(config)
        target = make_plans(config, mock="mock-1", customer=CODE)["targets"][0]
        self.assertEqual(config, unchanged)
        results = {r["product_class"]: r for r in target["resolved_profiles"]}
        self.assertEqual(results["Inherited"]["request_profile_source"], "customer")
        self.assertEqual(results["Read"]["method"], "GET")
        self.assertEqual(results["Read"]["probe_body"], {"type": "none"})
        self.assertEqual(results["Reset"]["probe_body"], {"type": "json", "value": {}})
        self.assertEqual(results["Reset"]["request_profile_source"], "product")
        self.assertTrue(all(set(m["request"]) == {"method", "urlPath"} for m in target["mappings"]))

    def test_method_changes_keep_mapping_ids_and_ownership(self):
        before = self.plan()
        self.raw["customers"][CODE]["request_profile"] = "read"
        after = self.plan()
        self.assertEqual([(m["id"], m["metadata"]) for m in before["mappings"]],
                         [(m["id"], m["metadata"]) for m in after["mappings"]])
        self.assertTrue(all(m["request"]["method"] == "GET" for m in after["mappings"]))

    def test_response_default_follows_resolved_response_and_explicit_precedence(self):
        customer = self.raw["customers"][CODE]
        customer.update(response_profile="empty-ok", ProductClasses={
            "Inherited": None, "Other": {"response_profile": "accepted"},
            "Explicit": {"request_profile": "default"}})
        self.raw["response_profiles"]["empty-ok"]["request_profile"] = "read"
        self.raw["response_profiles"]["accepted"]["request_profile"] = "submit"
        target = self.plan()
        resolved = {r["product_class"]: r for r in target["resolved_profiles"]}
        self.assertEqual((resolved["Inherited"]["request_profile"], resolved["Inherited"]["request_profile_source"]),
                         ("read", "response-profile"))
        self.assertEqual(resolved["Other"]["request_profile"], "submit")
        self.assertEqual(resolved["Explicit"]["request_profile"], "default")
        self.assertTrue(all("request_profile" not in m["response"] for m in target["mappings"]))
        customer["request_profile"] = "text"
        resolved = {r["product_class"]: r for r in self.plan()["resolved_profiles"]}
        self.assertEqual((resolved["Inherited"]["request_profile"], resolved["Inherited"]["request_profile_source"]),
                         ("text", "customer"))
        self.assertEqual(resolved["Other"]["request_profile"], "text")
        self.assertEqual((resolved["Explicit"]["request_profile"], resolved["Explicit"]["request_profile_source"]),
                         ("default", "product"))
        customer.pop("request_profile")
        self.raw["response_profiles"]["accepted"].pop("request_profile")
        resolved = {r["product_class"]: r for r in self.plan()["resolved_profiles"]}
        self.assertEqual((resolved["Other"]["request_profile"], resolved["Other"]["request_profile_source"]),
                         ("default", "default"))

    def test_error_and_timeout_profiles_retain_normal_response_request(self):
        self.raw["response_profiles"]["empty-ok"]["request_profile"] = "text"
        self.raw["response_profiles"]["accepted"]["request_profile"] = "read"
        normal = self.plan()
        for error in ("server-error", "timeout", "none"):
            with self.subTest(error=error):
                target = make_plans(self.load(), mock="mock-1", customer=CODE, profile=error)["targets"][0]
                self.assertEqual([m["request"] for m in target["mappings"]], [m["request"] for m in normal["mappings"]])
                self.assertEqual([r["probe_body"] for r in target["resolved_profiles"]],
                                 [r["probe_body"] for r in normal["resolved_profiles"]])
                self.assertTrue(all("request_profile" not in m["response"] for m in target["mappings"]))

    def test_response_default_link_validation_including_unused_profiles(self):
        original = copy.deepcopy(self.raw)
        for value in (None, "", "unknown", [], True):
            self.raw = copy.deepcopy(original)
            self.raw["response_profiles"]["unused"] = {"status": 200, "headers": {}, "body": "", "request_profile": value}
            with self.subTest(value=value), self.assertRaises(ConfigError):
                self.load()
        self.raw = copy.deepcopy(original)
        self.raw["response_profiles"]["empty-ok"]["request_profile"] = "default"
        self.raw["request_profiles"] = {}
        resolved = {r["product_class"]: r for r in self.plan()["resolved_profiles"]}
        self.assertEqual(resolved["Productclass"]["request_profile_source"], "response-profile")
        self.raw["error_profiles"]["server-error"]["response"]["request_profile"] = "default"
        with self.assertRaises(ConfigError):
            self.load()

    def test_shared_customer_routes_require_one_request_profile(self):
        customer = self.raw["customers"][CODE]
        customer.update(endpoint_scope="customer", request_profile="submit",
                        ProductClasses={"One": None, "Two": {"request_profile": "submit"}})
        target = self.plan()
        self.assertEqual(len(target["mappings"]), 1)
        self.assertEqual(target["resolved_profiles"][0]["request_profile_source"], "mixed")
        # Same method but different payload/profile must not silently deduplicate.
        customer["ProductClasses"]["Two"]["request_profile"] = "default"
        with self.assertRaisesRegex(ConfigError, "Conflicting request profiles"):
            self.plan()
        customer["ProductClasses"]["Two"]["request_profile"] = "read"
        with self.assertRaisesRegex(ConfigError, "Conflicting request methods"):
            self.plan()

    def test_distinct_customers_can_share_path_with_different_methods(self):
        for customer in self.raw["customers"].values():
            customer.update(endpoint_scope="customer", customer_path_override="shared", ProductClasses={})
        self.raw["customers"][CODE]["request_profile"] = "read"
        target = make_plans(self.load(), mock="mock-1", all_customers=True)["targets"][0]
        self.assertEqual(len(target["mappings"]), 2)
        self.assertEqual({m["request"]["method"] for m in target["mappings"]}, {"GET", "POST"})

    def test_invalid_definitions_and_unselected_references_fail_before_http(self):
        original = copy.deepcopy(self.raw)
        mutations = [
            lambda c: c.update(request_profiles=None),
            lambda c: c["request_profiles"].update(default=c["request_profiles"]["submit"]),
            lambda c: c["request_profiles"]["read"].update(probe_body={"type": "json", "value": {}}),
            lambda c: c["request_profiles"]["submit"].pop("probe_body"),
            lambda c: c["request_profiles"]["submit"].pop("method"),
            lambda c: c["customers"][CODE].update(request_method="POST"),
            lambda c: c["customers"][CODE]["ProductClasses"].update(Productclass={"probe_body": {"type": "none"}}),
        ]
        for method in (None, "post", "ANY", "TRACE", "CONNECT", []):
            mutations.append(lambda c, v=method: c["request_profiles"]["submit"].update(method=v))
        for body in (None, {}, {"type": "none", "value": ""}, {"type": "text", "value": 1},
                     {"type": "json"}, {"type": "json", "value": float("nan")}, {"type": "file", "value": "x"}):
            mutations.append(lambda c, v=body: c["request_profiles"]["submit"].update(probe_body=v))
        for selection in (None, "", "missing", [], True):
            mutations.extend([
                lambda c, v=selection: c["customers"][CODE].update(request_profile=v),
                lambda c, v=selection: c["customers"][CODE]["ProductClasses"].update(Productclass={"request_profile": v})])
        for mutate in mutations:
            self.raw = copy.deepcopy(original)
            mutate(self.raw)
            self.path.write_text(yaml.safe_dump(self.raw))
            with self.subTest(config=self.raw), patch("wiremock_benchmark_cli.api.WireMockAdmin.request") as http:
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(main(["apply", "-f", str(self.path), "--mock", "mock-1",
                                           "--customer", "3243423434"]), 2)
                http.assert_not_called()


class RequestProbeTest(unittest.TestCase):
    def test_payload_encoding_distinguishes_json_text_and_absent_body(self):
        for value in ({"text": "café", "enabled": True}, [1, "two"], None, False, 3.5, "text"):
            with self.subTest(value=value):
                body, headers = probe_payload({"probe_body": {"type": "json", "value": value}})
                self.assertEqual(json.loads(body), value)
                self.assertEqual(headers["Content-Type"], "application/json")
        body, headers = probe_payload({"probe_body": {"type": "text", "value": "café\n"}})
        self.assertEqual(body, "café\n".encode())
        self.assertEqual(headers["Content-Type"], "text/plain; charset=utf-8")
        body, headers = probe_payload({"probe_body": {"type": "none"}})
        self.assertIsNone(body)
        self.assertNotIn("Content-Type", headers)
        body, _ = probe_payload({"probe_body": {"type": "text", "value": ""}})
        self.assertEqual(body, b"")

    def test_public_http_probe_uses_configured_method_bytes_and_content_type(self):
        received = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def handle_probe(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                received.append((self.command, self.path, body, self.headers.get("Content-Type")))
                response = b'{"ok": true}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(response)

            do_GET = do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = handle_probe

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        cases = [("GET", {"type": "none"}, b"", None),
                 ("HEAD", {"type": "none"}, b"", None),
                 ("POST", {"type": "json", "value": {"a": 1}}, b'{"a": 1}', "application/json"),
                 ("PUT", {"type": "text", "value": "café"}, "café".encode(), "text/plain; charset=utf-8"),
                 ("PATCH", {"type": "json", "value": [1, True]}, b'[1, true]', "application/json"),
                 ("DELETE", {"type": "none"}, b"", None),
                 ("OPTIONS", {"type": "none"}, b"", None),
                 ("POST", {"type": "none"}, b"", None)]
        for method, body, expected_bytes, content_type in cases:
            mapping = {"id": "fixture", "request": {"method": method, "urlPath": "/public"},
                       "response": {"status": 200, "headers": {"Content-Type": "application/json"},
                                    "jsonBody": {"ok": True}, "fixedDelayMilliseconds": 0}}
            with self.subTest(method=method, body=body):
                passed, detail = probe(f"http://127.0.0.1:{server.server_port}/public", mapping, 50, 1000,
                                       request_settings={"probe_body": body})
                self.assertTrue(passed, detail)
                self.assertEqual(received[-1], (method, "/public", expected_bytes, content_type))
                if method == "HEAD":
                    self.assertIn("empty for HEAD", "\n".join(expected_criteria(mapping, 50, 1000)))


if __name__ == "__main__":
    unittest.main()
