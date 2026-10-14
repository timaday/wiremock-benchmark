"""Behavioral checks for the customer CLI, including real HTTP admin failures."""

import contextlib
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import yaml

from tools.wb_api import AdminError, apply_plans, mapping_matches
from tools.wb_cli import main
from tools.wb_config import ConfigError, api_base, load_config
from tools.wb_plan import make_plans


ROOT = Path(__file__).resolve().parents[1]


def single_plan(config, **kwargs):
    return make_plans(config, mock="mock-1", **kwargs)["targets"][0]


class ConfigurationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "wb.yaml"
        self.raw = yaml.safe_load((ROOT / "wb.yaml").read_text())
        self.raw["customers"]["3243423434"]["name"] = "Test Customer"
        self.raw["customers"]["2342342"]["name"] = "Second Customer"
        for customer in self.raw["customers"].values():
            customer["response_profile"] = "accepted"

    def load(self, raw=None):
        self.path.write_text(yaml.safe_dump(self.raw if raw is None else raw))
        return load_config(self.path)

    def test_all_customers_exact_paths_and_success_body(self):
        plan = single_plan(self.load(), all_customers=True, delay=1000)
        self.assertEqual(len(plan["mappings"]), 3)
        self.assertIn("http://localhost:19081/mock-1/Test%20Customer/3243423434/productClasses/Productclass",
                      plan["request_urls"])
        for mapping in plan["mappings"]:
            self.assertFalse(mapping["request"]["urlPath"].startswith("/mock-1"))
            self.assertEqual(mapping["response"]["jsonBody"], self.raw["response_profiles"]["accepted"]["jsonBody"])
            self.assertEqual(mapping["response"]["fixedDelayMilliseconds"], 1000)

    def test_customer_subset_update_identity_and_restore(self):
        config = self.load()
        success = single_plan(config, customer="2342342", delay=6000)
        error = single_plan(config, customer="2342342", delay=1000, profile="server-error")
        timeout = single_plan(config, customer="2342342", profile="timeout")
        for plan in (success, error, timeout):
            self.assertEqual(len(plan["mappings"]), 2)
            self.assertEqual([m["id"] for m in plan["mappings"]], [m["id"] for m in success["mappings"]])
        self.assertEqual(error["mappings"][0]["response"]["status"], 500)
        self.assertEqual(error["mappings"][0]["response"]["jsonBody"]["txn_result"]["result"], "REJECTED")
        self.assertEqual(timeout["mappings"][0]["response"]["fixedDelayMilliseconds"], 60000)
        self.assertEqual(timeout["mappings"][0]["response"]["status"], 200)
        config["customers"]["2342342"]["name"] = "Renamed Customer"
        renamed = single_plan(config, customer="2342342", delay=1000)
        self.assertEqual(renamed["mappings"][0]["id"], success["mappings"][0]["id"])
        self.assertIn("/Renamed%20Customer/", renamed["mappings"][0]["request"]["urlPath"])
        self.assertEqual(config["response_profiles"]["accepted"], self.raw["response_profiles"]["accepted"])

    def test_path_punctuation_stays_literal_for_nginx(self):
        self.raw["customers"]["2342342"]["ProductClasses"] = {"C++": None, "Prödüct.v1": None}
        plan = single_plan(self.load(), customer="2342342", delay=0)
        self.assertTrue(plan["mappings"][0]["request"]["urlPath"].endswith("/C++"))
        self.assertTrue(plan["mappings"][1]["request"]["urlPath"].endswith("/Pr%C3%B6d%C3%BCct.v1"))

    def test_invalid_selection_and_delay_fail(self):
        for args in ({"delay": 0}, {"customer": "missing", "delay": 0},
                     {"customer": "2342342", "all_customers": True, "delay": 0},
                     {"all_customers": True}, {"all_customers": True, "delay": 1},
                     {"all_customers": True, "delay": True},
                     {"all_customers": True, "delay": 0, "profile": "typo"},
                     {"all_customers": True, "delay": 1000, "profile": "timeout"}):
            with self.subTest(args=args), self.assertRaises(ConfigError):
                single_plan(self.load(), **args)

    def test_all_customers_requires_delay_allowed_for_every_customer(self):
        self.raw["customers"]["2342342"]["delay"] = [0]
        with self.assertRaisesRegex(ConfigError, "not allowed"):
            single_plan(self.load(), all_customers=True, delay=1000)

    def test_strict_schema_and_malformed_inputs(self):
        changes = [
            lambda c: c.update(wiremock="typo"),
            lambda c: c["customers"]["2342342"].update(name="../bad"),
            lambda c: c["customers"]["2342342"].update(name="x%2fy"),
            lambda c: c["customers"]["2342342"].update(delay=[True]),
            lambda c: c["customers"]["2342342"].update(delay=[0, 0]),
            lambda c: c["customers"]["2342342"].update(ProductClasses=[]),
            lambda c: c["customers"]["2342342"].update(ProductClasses={"foo": {}}),
            lambda c: c["response_profiles"]["accepted"].update(status=100),
            lambda c: c["response_profiles"]["accepted"].update(jsonBody={"x": float("nan")}),
            lambda c: c["response_profiles"]["accepted"].update(jsonBody={1: "value"}),
            lambda c: c["response_profiles"]["accepted"].update(headers={"bad\nheader": "bad"}),
            lambda c: c["error_profiles"]["timeout"].update(delay=0),
            lambda c: c["error_profiles"]["timeout"].update(type="typo"),
            lambda c: c["error_profiles"]["server-error"]["response"].update(status=200),
        ]
        for change in changes:
            raw = copy.deepcopy(self.raw)
            change(raw)
            with self.subTest(raw=raw), self.assertRaises(ConfigError):
                self.load(raw)

    def test_yaml_duplicate_keys_and_unsafe_tags_rejected(self):
        for document in ("customers: {}\ncustomers: {}\n", "!!python/object:builtins.object {}",
                         "customers: [", "{[a, b]: 1}"):
            self.path.write_text(document)
            with self.subTest(document=document), self.assertRaises(ConfigError):
                load_config(self.path)

    def test_numeric_codes_and_leading_zero_strings(self):
        customer = self.raw["customers"].pop("3243423434")
        self.raw["customers"][3243423434] = customer
        self.raw["customers"]["00123"] = copy.deepcopy(customer)
        self.raw["wiremocks"]["mock-1"]["customers"].append("00123")
        config = self.load()
        plan = single_plan(config, customer="00123", delay=0)
        self.assertIn("/00123/", plan["mappings"][0]["request"]["urlPath"])
        self.assertIn("3243423434", config["customers"])
        self.raw["customers"]["3243423434"] = customer
        with self.assertRaisesRegex(ConfigError, "Duplicate customer code"):
            self.load()

    def test_url_validation_and_override(self):
        self.assertEqual(api_base("https://host:443/mock-1/"), "https://host:443/mock-1")
        for value in ("ftp://host", "http://host:0", "http://host:bad", "http://host:99999",
                      "http://a:b@host", "http://host?a=b", "http://host/#",
                      "http://host/__admin/mappings", "http://host/x/../y", "http://host/%2f", "http://ho st"):
            with self.subTest(value=value), self.assertRaises(ConfigError):
                api_base(value)
        config = self.load()
        config["wiremocks"]["mock-1"]["prefix_handling"] = "preserve"
        plan = single_plan(config, all_customers=True, delay=0, override="http://other:19002")
        self.assertTrue(all(u.startswith("http://other:19002/") for u in plan["request_urls"]))

    def test_prefix_handling_is_required_and_explicit(self):
        config = self.load()
        stripped = single_plan(config, all_customers=True, delay=0)
        self.assertIn("/mock-1", stripped["warnings"][0])
        config["wiremocks"]["mock-1"]["prefix_handling"] = "preserve"
        preserved = single_plan(config, all_customers=True, delay=0)
        self.assertEqual(preserved["warnings"], [])
        self.assertEqual(preserved["request_urls"], stripped["request_urls"])
        for keep, strip in zip(preserved["mappings"], stripped["mappings"]):
            self.assertEqual(keep["request"]["urlPath"], "/mock-1" + strip["request"]["urlPath"])
            self.assertEqual(keep["id"], strip["id"])
        with self.assertRaisesRegex(ConfigError, "requires a URL path prefix"):
            single_plan(self.load(), all_customers=True, delay=0, override="http://direct:8080")
        for mode in (None, "auto"):
            raw = copy.deepcopy(self.raw)
            if mode is None:
                del raw["wiremocks"]["mock-1"]["prefix_handling"]
            else:
                raw["wiremocks"]["mock-1"]["prefix_handling"] = mode
            with self.subTest(mode=mode), self.assertRaises(ConfigError):
                self.load(raw)

    def test_dry_run_has_no_http_and_invalid_config_has_no_http(self):
        self.load()
        with patch("tools.wb_cli.apply_plans") as apply, contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(main(["--config", str(self.path), "--mock", "mock-1", "--all-customers", "--delay", "0", "--dry-run"]), 0)
            self.assertEqual(len(json.loads(output.getvalue())["targets"][0]["mappings"]), 3)
            self.assertIn("WARNING [mock-1]:", errors.getvalue())
            self.assertIn("/mock-1", errors.getvalue())
            apply.assert_not_called()
        with patch("tools.wb_cli.apply_plans") as apply, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["--config", str(self.path), "--mock", "mock-1", "--all-customers", "--delay", "1"]), 2)
            apply.assert_not_called()

    def test_all_mocks_apply_only_their_assignments(self):
        self.raw["wiremocks"]["mock-1"]["customers"] = ["3243423434"]
        plan = make_plans(self.load(), all_mocks=True, all_customers=True, delay=1000)
        self.assertEqual(len(plan["targets"]), 5)
        self.assertEqual(plan["targets"][0]["customers"], ["3243423434"])
        self.assertEqual(len(plan["targets"][0]["mappings"]), 1)
        self.assertEqual(len(plan["targets"][1]["mappings"]), 3)

    def test_groups_route_only_to_assignments_and_report_empty_targets(self):
        self.raw["wiremocks"]["mock-1"]["customers"] = ["3243423434"]
        plan = make_plans(self.load(), all_mocks=True, group="slow-customers", delay=6000)
        self.assertEqual(plan["targets"][0]["customers"], [])
        self.assertEqual(plan["targets"][0]["mappings"], [])
        self.assertIn("will not be contacted", plan["targets"][0]["warnings"][-1])
        for target in plan["targets"][1:]:
            self.assertEqual(target["customers"], ["2342342"])
            self.assertEqual(len(target["mappings"]), 2)

    def test_group_can_span_disjoint_assignments(self):
        self.raw["wiremocks"] = {key: self.raw["wiremocks"][key] for key in ("mock-1", "mock-2")}
        self.raw["wiremocks"]["mock-1"]["customers"] = ["3243423434"]
        self.raw["wiremocks"]["mock-2"]["customers"] = ["2342342"]
        plan = make_plans(self.load(), all_mocks=True, group="test-customers", delay=1000)
        self.assertEqual([t["customers"] for t in plan["targets"]], [["3243423434"], ["2342342"]])
        with self.assertRaisesRegex(ConfigError, "not assigned"):
            make_plans(self.load(), mock="mock-1", group="test-customers", delay=1000)

    def test_invalid_target_group_and_assignment_references_fail(self):
        changes = [
            lambda c: c.update(wiremocks={}),
            lambda c: c.update(customer_groups={"empty": []}),
            lambda c: c.update(customer_groups={"bad": ["missing"]}),
            lambda c: c.update(customer_groups={"bad": ["2342342", 2342342]}),
            lambda c: c["wiremocks"]["mock-1"].update(customers=[]),
            lambda c: c["wiremocks"]["mock-1"].update(customers=["missing"]),
            lambda c: c["wiremocks"]["mock-1"].update(customers=["2342342", 2342342]),
            lambda c: c["wiremocks"]["mock-1"].update(api="http://LOCALHOST:19081/mock-2/"),
            lambda c: c.update(wiremock_api="http://old:8080"),
        ]
        for change in changes:
            raw = copy.deepcopy(self.raw)
            change(raw)
            with self.subTest(raw=raw), self.assertRaises(ConfigError):
                self.load(raw)

    def test_selection_must_be_explicit_and_override_requires_one_mock(self):
        for args in ({}, {"mock": "missing"}, {"mock": "mock-1", "all_mocks": True},
                     {"all_mocks": True, "override": "http://host:8080"}):
            with self.subTest(args=args), self.assertRaises(ConfigError):
                make_plans(self.load(), all_customers=True, delay=1000, **args)
        with self.assertRaisesRegex(ConfigError, "Unknown group"):
            make_plans(self.load(), mock="mock-1", group="missing", delay=0)
        with self.assertRaises(ConfigError):
            make_plans(self.load(), mock="mock-1", group="slow-customers", customer="2342342", delay=0)

    def test_invalid_later_mock_delay_prevents_all_http(self):
        self.raw["wiremocks"]["mock-1"]["customers"] = ["3243423434"]
        self.raw["customers"]["2342342"]["delay"] = [0]
        self.load()
        with patch("tools.wb_cli.apply_plans") as apply, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["--config", str(self.path), "--all-mocks", "--group", "test-customers",
                                   "--delay", "1000"]), 2)
            apply.assert_not_called()

    def test_customer_profile_inheritance_and_explicit_product_override(self):
        self.raw["customers"]["2342342"]["response_profile"] = "empty-ok"
        plan = single_plan(self.load(), customer="2342342", delay=1000)
        by_product = {m["metadata"]["wb"]["productClass"]: m for m in plan["mappings"]}
        self.assertEqual(by_product["Productclass"]["response"],
                         {"status": 200, "headers": {}, "body": "", "fixedDelayMilliseconds": 1000})
        self.assertEqual(by_product["AnotherProduct"]["response"]["jsonBody"],
                         self.raw["response_profiles"]["accepted"]["jsonBody"])
        origins = {entry["product_class"]: (entry["response_profile"], entry["source"])
                   for entry in plan["resolved_profiles"]}
        self.assertEqual(origins, {"Productclass": ("empty-ok", "customer"),
                                  "AnotherProduct": ("accepted", "product")})
        self.raw["customers"]["2342342"]["response_profile"] = "accepted"
        updated = single_plan(self.load(), customer="2342342", delay=1000)
        self.assertEqual([m["id"] for m in plan["mappings"]], [m["id"] for m in updated["mappings"]])
        self.assertTrue(all("jsonBody" in m["response"] and "body" not in m["response"] for m in updated["mappings"]))

    def test_error_replaces_complete_response_and_timeout_retains_each_body(self):
        self.raw["customers"]["2342342"]["response_profile"] = "empty-ok"
        self.raw["response_profiles"]["accepted"]["headers"]["X-Success"] = "remove-on-error"
        original = copy.deepcopy(self.raw)
        config = self.load()
        error = single_plan(config, customer="2342342", delay=0, profile="server-error")
        for mapping in error["mappings"]:
            self.assertEqual(mapping["response"], dict(self.raw["error_profiles"]["server-error"]["response"],
                                                       fixedDelayMilliseconds=0))
            self.assertNotIn("body", mapping["response"])
        timeout = single_plan(config, customer="2342342", profile="timeout")
        for mapping in timeout["mappings"]:
            response = mapping["response"]
            self.assertEqual(response["fixedDelayMilliseconds"], 60000)
            if mapping["metadata"]["wb"]["productClass"] == "Productclass":
                self.assertEqual(response["body"], "")
                self.assertEqual(response["headers"], {})
            else:
                self.assertEqual(response["headers"]["X-Success"], "remove-on-error")
                self.assertIn("jsonBody", response)
        self.assertEqual(config, original)

    def test_response_profiles_fail_on_missing_or_ambiguous_definitions(self):
        changes = [
            lambda c: c.update(response_profiles={}),
            lambda c: c.update(response={}),
            lambda c: c["customers"]["2342342"].pop("response_profile"),
            lambda c: c["customers"]["2342342"].update(response_profile="missing"),
            lambda c: c["customers"]["2342342"].update(response_profile=None),
            lambda c: c["customers"]["2342342"]["ProductClasses"].update(AnotherProduct={"response_profile": "missing"}),
            lambda c: c["customers"]["2342342"]["ProductClasses"].update(AnotherProduct={"response_profile": None}),
            lambda c: c["response_profiles"]["empty-ok"].pop("body"),
            lambda c: c["response_profiles"]["empty-ok"].update(jsonBody={}),
            lambda c: c["response_profiles"]["empty-ok"].update(body=None),
            lambda c: c["response_profiles"]["empty-ok"].pop("headers"),
            lambda c: c["response_profiles"]["accepted"].update(status=204),
            lambda c: c["error_profiles"]["server-error"]["response"].pop("headers"),
        ]
        for change in changes:
            raw = copy.deepcopy(self.raw)
            change(raw)
            with self.subTest(raw=raw), self.assertRaises(ConfigError):
                self.load(raw)

    def test_text_body_and_empty_error_response_are_supported(self):
        self.raw["response_profiles"]["accepted"] = {"status": 200, "headers": {"Content-Type": "text/plain"}, "body": "OK"}
        self.raw["error_profiles"]["server-error"]["response"] = {"status": 503, "headers": {}, "body": ""}
        config = self.load()
        plan = single_plan(config, customer="2342342", delay=0)
        self.assertTrue(all(m["response"]["body"] == "OK" for m in plan["mappings"]))
        error = single_plan(config, customer="2342342", delay=0, profile="server-error")
        self.assertTrue(all(m["response"] == {"status": 503, "headers": {}, "body": "", "fixedDelayMilliseconds": 0}
                            for m in error["mappings"]))

    def test_unknown_profile_on_unselected_customer_prevents_http(self):
        self.raw["customers"]["2342342"]["response_profile"] = "missing"
        self.path.write_text(yaml.safe_dump(self.raw))
        with patch("tools.wb_cli.apply_plans") as apply, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["--config", str(self.path), "--mock", "mock-1", "--customer", "3243423434",
                                   "--delay", "1000"]), 2)
            apply.assert_not_called()


class ResponseReadbackTest(unittest.TestCase):
    def test_rejects_stale_body_types_headers_and_json_properties(self):
        expected = {"id": "test", "response": {"status": 200, "headers": {}, "body": "", "fixedDelayMilliseconds": 0}}
        self.assertTrue(mapping_matches(copy.deepcopy(expected), expected))
        for extra in ({"jsonBody": {"old": "body"}}, {"base64Body": "b2xk"}, {"bodyFileName": "old.json"},
                      {"headers": {"Content-Type": "application/json"}}, {"body": "old"}):
            actual = copy.deepcopy(expected)
            actual["response"].update(extra)
            with self.subTest(extra=extra):
                self.assertFalse(mapping_matches(actual, expected))
        expected["response"].pop("body")
        expected["response"]["jsonBody"] = {"success": True}
        actual = copy.deepcopy(expected)
        actual["response"]["jsonBody"]["old"] = "field"
        self.assertFalse(mapping_matches(actual, expected))


class AdminHttpTest(unittest.TestCase):
    def setUp(self):
        self.state = {"unrelated": {"id": "unrelated", "request": {"urlPath": "/keep"}}}
        self.calls = []
        self.failure = None
        self.corrupt = False
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def handle_request(self):
                owner.calls.append((self.command, self.path))
                if owner.failure:
                    failure = owner.failure(self.command, self.path)
                    if failure:
                        self.send_response(failure)
                        self.send_header("Location", "/redirected")
                        self.end_headers()
                        return
                identifier = self.path.rsplit("/", 1)[-1]
                if self.command == "GET":
                    body = owner.state.get(identifier)
                    status = 200 if body is not None else 404
                else:
                    body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                    owner.state[body["id"]] = body
                    if owner.corrupt:
                        body["response"]["fixedDelayMilliseconds"] = 42
                    status = 201 if self.command == "POST" else 200
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(body).encode())

            do_GET = do_POST = do_PUT = handle_request

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.plan = single_plan(load_config(ROOT / "wb.yaml"), all_customers=True, delay=0,
                              override=f"http://127.0.0.1:{self.server.server_port}/mock-1")

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def apply(self):
        return apply_plans({"targets": [self.plan]}, 2, progress=lambda message: None)

    def test_create_reapply_and_update_preserve_unrelated_mapping(self):
        unrelated = copy.deepcopy(self.state["unrelated"])
        self.assertEqual(self.apply(), 3)
        self.assertEqual(self.apply(), 3)
        for mapping in self.plan["mappings"]:
            mapping["response"]["fixedDelayMilliseconds"] = 6000
        self.assertEqual(self.apply(), 3)
        self.assertEqual(len(self.state), 4)
        self.assertEqual(self.state["unrelated"], unrelated)
        self.assertTrue(all(path.startswith("/mock-1/__admin/mappings") for _, path in self.calls))
        self.assertEqual(sum(method == "POST" for method, _ in self.calls), 3)
        self.assertEqual(sum(method == "PUT" for method, _ in self.calls), 6)
        self.assertEqual(self.state[self.plan["mappings"][0]["id"]]["response"]["fixedDelayMilliseconds"], 6000)

    def test_foreign_id_collision_fails_preflight_before_any_write(self):
        last = self.plan["mappings"][-1]
        self.state[last["id"]] = {"id": last["id"], "metadata": {"owner": "someone else"}}
        with self.assertRaisesRegex(AdminError, "ownership mismatch"):
            self.apply()
        self.assertTrue(all(method == "GET" for method, _ in self.calls))

    def test_partial_failure_reports_count_and_rerun_converges(self):
        self.failure = lambda method, path: 503 if method == "POST" and len(self.state) == 2 else None
        with self.assertRaisesRegex(AdminError, "Verified 1/3"):
            self.apply()
        self.assertEqual(len(self.state), 2)
        self.failure = None
        self.assertEqual(self.apply(), 3)
        self.assertEqual(len(self.state), 4)

    def test_redirect_and_auth_failure_are_not_followed_or_retried(self):
        for status in (302, 401, 403):
            self.calls.clear()
            self.failure = lambda method, path: status
            with self.subTest(status=status), self.assertRaisesRegex(AdminError, f"HTTP {status}"):
                self.apply()
            self.assertEqual(len(self.calls), 1)

    def test_server_readback_mismatch_fails(self):
        self.corrupt = True
        with self.assertRaisesRegex(AdminError, "Readback mismatch"):
            self.apply()

    def two_target_plan(self):
        second = copy.deepcopy(self.plan)
        second["mock"] = "mock-2"
        second["wiremock_api"] = second["wiremock_api"].replace("/mock-1", "/mock-2")
        return {"targets": [self.plan, second]}

    def test_later_target_preflight_failure_prevents_earlier_writes(self):
        plan = self.two_target_plan()
        self.failure = lambda method, path: 503 if path.startswith("/mock-2/") else None
        with self.assertRaisesRegex(AdminError, r"\[mock-2\] preflight failed.*No writes attempted"):
            apply_plans(plan, 2)
        self.assertTrue(all(method == "GET" for method, _ in self.calls))
        self.assertEqual(len(self.state), 1)

    def test_later_write_failure_identifies_completed_target(self):
        plan = self.two_target_plan()
        self.failure = lambda method, path: 503 if method == "POST" and path.startswith("/mock-2/") else None
        with self.assertRaisesRegex(AdminError, r"\[mock-2\] write failed.*Verified 3/6; completed targets: mock-1"):
            apply_plans(plan, 2, progress=lambda message: None)
        first_write = next(i for i, (method, _) in enumerate(self.calls) if method == "POST")
        self.assertEqual(first_write, 6)

    def test_empty_target_is_reported_without_contact(self):
        plan = self.two_target_plan()
        plan["targets"][1]["mappings"] = []
        messages = []
        self.assertEqual(apply_plans(plan, 2, progress=messages.append), 3)
        self.assertTrue(any("[mock-2] No matching" in line for line in messages))
        self.assertTrue(all(path.startswith("/mock-1/") for _, path in self.calls))


class ConfigFileOptionTest(unittest.TestCase):
    def test_short_option_selects_file_for_all_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wb.phase1.yaml"
            config = yaml.safe_load((ROOT / "wb.yaml").read_text())
            config["customers"]["3243423434"]["name"] = "PhaseOneCustomer"
            path.write_text(yaml.safe_dump(config))
            for command, flags in (([], ["--all-mocks", "--delay", "0", "--dry-run"]),
                                   (["list"], []), (["verify"], ["--delay", "0"])):
                with self.subTest(command=command), patch("tools.wb_verify.verify_plans", return_value=[{"passed": True}]) as verify:
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
                        self.assertEqual(main([*command, "-f", str(path), "--all-customers", *flags]), 0)
                    if command == ["verify"]:
                        plan = verify.call_args.args[0]
                        self.assertIn("PhaseOneCustomer", json.dumps(plan))
                    else:
                        self.assertIn("PhaseOneCustomer", output.getvalue())

    def test_missing_selected_file_does_not_use_default(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.yaml"
            for command, flags in (([], ["--all-mocks", "--delay", "0", "--dry-run"]),
                                   (["list"], []), (["verify"], ["--delay", "0"])):
                with self.subTest(command=command), contextlib.redirect_stderr(io.StringIO()), patch("tools.wb_api.WireMockAdmin.request") as http:
                    self.assertEqual(main([*command, "-f", str(path), "--all-customers", *flags]), 2)
                    http.assert_not_called()


if __name__ == "__main__":
    unittest.main()
