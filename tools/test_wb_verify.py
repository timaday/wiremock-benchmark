"""Check verification verdicts, HTTP behavior and absence of admin writes."""

import contextlib
import copy
from email.message import Message
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import yaml

from tools.wb_cli import main
from tools.wb_api import AdminError
from tools.wb_config import load_config
from tools.wb_plan import make_plans
from tools.wb_verify import probe, response_problem, verify_plans
from tools.wb_verify_expectations import expected_criteria


ROOT = Path(__file__).resolve().parents[1]


def headers(values):
    result = Message()
    for name, value in values.items():
        result[name] = value
    return result


class ResponseChecksTest(unittest.TestCase):
    def test_expected_criteria_show_literal_body_and_custom_timing(self):
        mapping = {"id": "example", "request": {"method": "POST", "urlPath": "/example"},
                   "response": {"status": 200, "body": "hello\nworld", "headers": {"Content-Type": "text/plain"},
                                "fixedDelayMilliseconds": 1000}}
        text = "\n".join(expected_criteria(mapping, 25, 250))
        self.assertIn('exact match "hello\\nworld"', text)
        self.assertIn('11 UTF-8 bytes', text)
        self.assertIn('975.0–1250.0ms', text)
        self.assertIn('"Content-Type": "text/plain"', text)
        self.assertNotIn('Content-Type: absent', text)

    def test_network_timeout_is_failure_even_for_delayed_success(self):
        mapping = {"request": {"method": "POST"}, "response": {
            "status": 200, "body": "", "headers": {}, "fixedDelayMilliseconds": 60000}}
        with patch("tools.wb_verify.build_opener") as opener:
            opener.return_value.open.side_effect = TimeoutError()
            passed, detail = probe("http://unused.test/endpoint", mapping, 50, 1000)
        self.assertFalse(passed)
        self.assertIn("connection/read timed out", detail)

    def test_empty_requires_zero_bytes_and_no_unconfigured_content_type(self):
        expected = dict(status=200, body="", headers={}, fixedDelayMilliseconds=0)
        self.assertIsNone(response_problem(expected, 200, headers({"Date": "today"}), b"", 1, 50, 1000))
        self.assertIn("body bytes", response_problem(expected, 200, headers({}), b" ", 1, 50, 1000))
        self.assertIn("Content-Type", response_problem(expected, 200, headers({"Content-Type": "application/json"}), b"", 1, 50, 1000))

    def test_json_checks_content_types_and_duplicate_keys(self):
        expected = dict(status=200, jsonBody={"a": True, "b": "ok"}, headers={"Content-Type": "application/json"}, fixedDelayMilliseconds=0)
        actual_headers = headers({"content-type": "application/json"})
        self.assertIsNone(response_problem(expected, 200, actual_headers, b'{ "b": "ok", "a": true }', 1, 50, 1000))
        for body in (b'{"a":1,"b":"ok"}', b'{"a":false,"a":true,"b":"ok"}', b'{"a":NaN}', b'not json'):
            with self.subTest(body=body):
                self.assertIsNotNone(response_problem(expected, 200, actual_headers, body, 1, 50, 1000))
        self.assertIn("header", response_problem(expected, 200, headers({}), b'{}', 1, 50, 1000))

    def test_timing_bounds_and_status(self):
        expected = dict(status=200, body="OK", headers={}, fixedDelayMilliseconds=6000)
        for elapsed in (5950, 6000, 7000):
            self.assertIsNone(response_problem(expected, 200, headers({}), b"OK", elapsed, 50, 1000))
        for elapsed in (5949, 7001):
            self.assertIn("response time", response_problem(expected, 200, headers({}), b"OK", elapsed, 50, 1000))
        self.assertIn("HTTP status", response_problem(expected, 404, headers({}), b"OK", 6000, 50, 1000))


class VerificationHttpTest(unittest.TestCase):
    def setUp(self):
        self.config = load_config(ROOT / "wb.yaml")
        self.calls = []
        self.tamper = None
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                owner.calls.append(("GET", self.path, b""))
                value = owner.installed.get(self.path.rsplit("/", 1)[-1])
                self.send_response(200 if value is not None else 404)
                self.end_headers()
                self.wfile.write(json.dumps(value).encode())

            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                owner.calls.append(("POST", self.path, body))
                mapping = next(m for m in owner.plan["targets"][0]["mappings"] if m["request"]["urlPath"] == self.path)
                response = mapping["response"]
                payload = response["body"].encode() if "body" in response else json.dumps(response["jsonBody"], indent=2).encode()
                status, response_headers = response["status"], copy.deepcopy(response["headers"])
                if owner.tamper is not None:
                    status, response_headers, payload = owner.tamper(mapping, status, response_headers, payload)
                self.send_response(status)
                for name, value in response_headers.items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(payload)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.config["wiremocks"] = {"test": dict(api=f"http://127.0.0.1:{self.server.server_port}",
                                                 prefix_handling="preserve", customers=["2342342"])}
        self.plan = self.make_plan()
        self.installed = {m["id"]: copy.deepcopy(m) for m in self.plan["targets"][0]["mappings"]}

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def make_plan(self, profile=None):
        return make_plans(self.config, mock="test", customer="2342342", delay=0, profile=profile)

    def verify(self):
        return verify_plans(self.plan, progress=lambda message: None)

    def test_empty_and_json_pass_without_admin_writes(self):
        before = copy.deepcopy(self.installed)
        results = self.verify()
        self.assertEqual(len(results), 2)
        self.assertTrue(all(r["passed"] for r in results), results)
        self.assertEqual(before, self.installed)
        self.assertEqual([method for method, _, _ in self.calls], ["GET", "POST", "GET", "POST"])
        self.assertTrue(all(body == b"{}" and not path.startswith("/__admin")
                            for method, path, body in self.calls if method == "POST"))

    def test_shared_customer_route_is_verified_once(self):
        customer = self.config["customers"]["2342342"]
        customer["endpoint_scope"] = "customer"
        customer["ProductClasses"] = {"One": None, "Two": None}
        self.plan = self.make_plan()
        self.installed = {m["id"]: copy.deepcopy(m) for m in self.plan["targets"][0]["mappings"]}
        results = self.verify()
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["passed"], results)
        self.assertEqual([method for method, _, _ in self.calls], ["GET", "POST"])
        self.assertTrue(self.calls[-1][1].endswith("/2342342"))

    def test_extension_override_is_probed_on_resolved_public_path(self):
        customer = self.config["customers"]["2342342"]
        customer["endpoint_scope"] = "customer"
        customer["uri_extension"] = "transactions"
        customer["customer_path_override"] = "partner/orders"
        customer["ProductClasses"] = {"One": None, "Two": {"endpoint_scope": "product-class", "uri_extension": "special/v1"}}
        self.plan = self.make_plan()
        self.installed = {m["id"]: copy.deepcopy(m) for m in self.plan["targets"][0]["mappings"]}
        self.assertTrue(all(result["passed"] for result in self.verify()))
        self.assertEqual([path for method, path, _ in self.calls if method == "POST"], [
            "/partner/orders/transactions", "/partner/orders/special/v1/productClasses/Two"])

    def test_customer_endpoint_without_products_is_probed_once(self):
        customer = self.config["customers"]["2342342"]
        customer.update(endpoint_scope="customer", ProductClasses={}, customer_path_override="partner/orders", uri_extension="transactions")
        self.plan = self.make_plan()
        self.installed = {m["id"]: copy.deepcopy(m) for m in self.plan["targets"][0]["mappings"]}
        results = self.verify()
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["passed"], results)
        self.assertEqual([path for method, path, _ in self.calls if method == "POST"], ["/partner/orders/transactions"])

    def test_each_endpoint_reports_expectations_before_check_and_verdict(self):
        output = []
        with patch("tools.wb_api.WireMockAdmin.request", side_effect=AdminError("unavailable")) as admin, patch("tools.wb_verify.probe") as probe:
            def progress(line):
                if line.startswith("CHECK"):
                    self.assertEqual(admin.call_count, sum(item.startswith("FAIL") for item in output))
                output.append(line)
            results = verify_plans(self.plan, progress=progress)
        probe.assert_not_called()
        self.assertEqual(len(results), 2)
        self.assertEqual(sum(line.startswith("CHECK") for line in output), 2)
        self.assertEqual(sum(line.startswith("FAIL") for line in output), 2)
        text = "\n".join(output)
        self.assertIn('Expected body: 0 UTF-8 bytes; exact match ""', text)
        self.assertIn('Expected Content-Type: absent', text)
        self.assertIn('JSON content/types must match', text)
        self.assertIn('Mocked success request', text)
        self.assertIn('Expected status: HTTP 200', text)
        self.assertIn('response time 0.0–1000.0ms', text)
        for mapping in self.plan['targets'][0]['mappings']:
            self.assertIn(mapping['id'], text)
            self.assertIn(mapping['request']['urlPath'], text)

    def test_mapping_mismatch_and_missing_mapping_fail_without_probe(self):
        first, second = list(self.installed)
        self.installed[first]["response"]["fixedDelayMilliseconds"] = 1000
        self.installed.pop(second)
        results = self.verify()
        self.assertTrue(all(not r["passed"] for r in results))
        self.assertTrue(all(method == "GET" for method, _, _ in self.calls))
        self.assertIn("differs", results[0]["detail"])
        self.assertIn("404", results[1]["detail"])

    def test_wrong_response_fails_and_checks_continue(self):
        self.tamper = lambda mapping, status, head, body: (status, head, b"not empty") if "body" in mapping["response"] else (status, head, body)
        results = self.verify()
        self.assertEqual([r["passed"] for r in results], [False, True])

    def test_expected_error_status_passes(self):
        self.plan = self.make_plan("server-error")
        self.installed = {m["id"]: copy.deepcopy(m) for m in self.plan["targets"][0]["mappings"]}
        self.assertTrue(all(r["passed"] for r in self.verify()))

    def test_redirect_is_not_followed(self):
        self.tamper = lambda mapping, status, head, body: (302, {"Location": "/unexpected"}, b"")
        self.assertTrue(all(not r["passed"] for r in self.verify()))
        self.assertFalse(any(path == "/unexpected" for _, path, _ in self.calls))

    def test_unreachable_admin_is_failure(self):
        with patch("tools.wb_api.WireMockAdmin.request", side_effect=AdminError("unavailable")), patch("tools.wb_verify.probe") as probe:
            self.assertTrue(all(not r["passed"] for r in self.verify()))
            probe.assert_not_called()

    def test_cli_and_missing_delay_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wb.yaml"
            path.write_text(yaml.safe_dump(self.config))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(["verify", "--config", str(path), "--customer", "2342342", "--delay", "0"]), 0)
            self.assertIn("2 passed, 0 failed", output.getvalue())
            with patch("tools.wb_verify.verify_plans") as verify, contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(["verify", "--config", str(path), "--customer", "2342342"]), 2)
                verify.assert_not_called()

    def test_invalid_time_limits_are_rejected_before_network(self):
        for flag, value in (("--admin-timeout", "0"), ("--early-tolerance-ms", "-1"),
                            ("--max-overhead-ms", "nan"), ("--max-overhead-ms", "inf")):
            with self.subTest(flag=flag, value=value), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main(["verify", "--customer", "2342342", "--delay", "0", flag, value])
            self.assertEqual(error.exception.code, 2)
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
