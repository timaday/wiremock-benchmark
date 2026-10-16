"""Check versioned repeatable profiles and delay precedence across targets."""

import contextlib
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import yaml

from wiremock_benchmark_cli.cli import main
from wiremock_benchmark_cli.config import ConfigError, load_config
from wiremock_benchmark_cli.plan import make_plans


ROOT = Path(__file__).resolve().parents[1]


class ProfilesV1Test(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "profile.yaml"
        self.raw = yaml.safe_load((ROOT / "wb.yaml").read_text())

    def load(self):
        self.path.write_text(yaml.safe_dump(self.raw, sort_keys=False))
        return load_config(self.path)

    def plan(self, **options):
        return make_plans(self.load(), all_mocks=True, all_customers=True, **options)

    def test_default_and_mock_delay_apply_per_customer_and_cli_zero_overrides_all(self):
        plan = self.plan()
        for target in plan["targets"]:
            for mapping, resolution in zip(target["mappings"], target["resolved_profiles"]):
                overridden = target["mock"] == "mock-2" and resolution["customer"] == "2342342"
                self.assertEqual(mapping["response"]["fixedDelayMilliseconds"], 6000 if overridden else 1000)
                self.assertEqual(resolution["delay_source"], "mock-customer" if overridden else "customer")
        override = self.plan(delay=0)
        for original, updated in zip(plan["targets"], override["targets"]):
            self.assertEqual([m["id"] for m in original["mappings"]], [m["id"] for m in updated["mappings"]])
            self.assertTrue(all(m["response"]["fixedDelayMilliseconds"] == 0 for m in updated["mappings"]))
            self.assertTrue(all(r["delay_source"] == "cli" for r in updated["resolved_profiles"]))
        self.raw["wiremocks"]["mock-2"]["customers"]["2342342"]["delay_ms"] = 0
        target = self.plan()["targets"][1]
        self.assertEqual([r["delay_ms"] for r in target["resolved_profiles"] if r["customer"] == "2342342"], [0, 0])

    def test_unconstrained_delay_and_optional_allowlist(self):
        for customer in self.raw["customers"].values():
            customer.pop("allowed_delays_ms")
            customer["delay_ms"] = 17
        self.assertEqual(self.plan()["targets"][0]["mappings"][0]["response"]["fixedDelayMilliseconds"], 17)
        self.assertTrue(all(m["response"]["fixedDelayMilliseconds"] == 23
                            for t in self.plan(delay=23)["targets"] for m in t["mappings"]))
        self.raw["customers"]["2342342"]["allowed_delays_ms"] = [17, 6000]
        with self.assertRaisesRegex(ConfigError, "not allowed"):
            self.plan(delay=23)

    def test_http_error_uses_normal_delays_timeout_bypasses_allowlist_explicitly(self):
        targets = self.plan(profile="server-error")["targets"]
        self.assertEqual(targets[1]["mappings"][1]["response"]["fixedDelayMilliseconds"], 6000)
        self.assertTrue(all(m["response"]["status"] == 500 for t in targets for m in t["mappings"]))
        targets = self.plan(profile="timeout")["targets"]
        self.assertTrue(all(r["delay_ms"] == 60000 and r["delay_source"] == "timeout-profile"
                            for t in targets for r in t["resolved_profiles"]))
        with self.assertRaisesRegex(ConfigError, "omit --delay"):
            self.plan(delay=0, profile="timeout")

    def test_required_integer_schema_version_rejected_by_every_command(self):
        original = copy.deepcopy(self.raw)
        for version in (None, True, "1", 1.0, 0, 2):
            self.raw = copy.deepcopy(original)
            if version is None:
                self.raw.pop("schema_version")
            else:
                self.raw["schema_version"] = version
            self.path.write_text(yaml.safe_dump(self.raw))
            for command in (["apply", "--all-mocks"], ["list"], ["verify"], ["clean", "--all-mocks"]):
                with self.subTest(version=version, command=command), patch("wiremock_benchmark_cli.api.WireMockAdmin.request") as http:
                    with contextlib.redirect_stderr(io.StringIO()) as errors:
                        self.assertEqual(main([*command, "-f", str(self.path), "--all-customers"]), 2)
                    self.assertIn("schema_version", errors.getvalue())
                    http.assert_not_called()

    def test_legacy_fields_and_invalid_assignment_values_are_not_reinterpreted(self):
        original = copy.deepcopy(self.raw)
        mutations = [
            lambda c: c["customers"]["2342342"].pop("delay_ms"),
            lambda c: c["customers"]["2342342"].update(delay=[0, 1000]),
            lambda c: c["customers"]["2342342"].update(delay_ms=True),
            lambda c: c["customers"]["2342342"].update(delay_ms=-1),
            lambda c: c["customers"]["2342342"].update(delay_ms=2147483648),
            lambda c: c["customers"]["2342342"].update(allowed_delays_ms=[]),
            lambda c: c["customers"]["2342342"].update(allowed_delays_ms=None),
            lambda c: c["customers"]["2342342"].update(allowed_delays_ms=[0, 0]),
            lambda c: c["wiremocks"]["mock-1"].update(customers=["2342342"]),
            lambda c: c["wiremocks"]["mock-1"].update(customers={"2342342": None}),
            lambda c: c["wiremocks"]["mock-1"].update(customers={"2342342": {"delay_ms": None}}),
            lambda c: c["wiremocks"]["mock-1"].update(customers={"2342342": {"delay_ms": False}}),
            lambda c: c["wiremocks"]["mock-1"].update(customers={"2342342": {"unknown": 1}}),
            lambda c: c["error_profiles"]["timeout"].update(delay=60000),
            lambda c: c["customers"]["2342342"]["ProductClasses"].update(AnotherProduct={"delay_ms": 1}),
        ]
        for mutate in mutations:
            self.raw = copy.deepcopy(original)
            mutate(self.raw)
            with self.subTest(config=self.raw), self.assertRaises(ConfigError):
                self.load()

    def test_default_and_unselected_target_constraints_are_checked_before_http(self):
        self.raw["wiremocks"]["mock-5"]["customers"]["2342342"] = {"delay_ms": 17}
        self.path.write_text(yaml.safe_dump(self.raw))
        with patch("wiremock_benchmark_cli.api.WireMockAdmin.request") as http, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["apply", "-f", str(self.path), "--mock", "mock-1", "--customer", "2342342"]), 2)
        http.assert_not_called()
        self.raw["wiremocks"]["mock-5"]["customers"]["2342342"] = {}
        self.raw["customers"]["2342342"]["delay_ms"] = 17
        with self.assertRaisesRegex(ConfigError, "not allowed"):
            self.load()

    def test_list_and_dry_run_show_file_delays_and_override_sources(self):
        self.load()
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["list", "-f", str(self.path), "--all-customers"]), 0)
        self.assertIn("delay=1000ms (customer)", output.getvalue())
        self.assertIn("delay=6000ms (mock-customer)", output.getvalue())
        for flags, source in (([], "customer"), (["--delay", "0"], "cli")):
            with contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(["apply", "-f", str(self.path), "--mock", "mock-1", "--all-customers", "--dry-run", *flags]), 0)
            plan = json.loads(output.getvalue())
            self.assertTrue(all(r["delay_source"] == source for r in plan["targets"][0]["resolved_profiles"]))

    def test_apply_and_verify_use_same_file_delays_over_http(self):
        state = {"mock-1": {}, "mock-2": {}}
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def reply(self, status, data=None, headers=None):
                self.send_response(status)
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                if data is not None:
                    self.wfile.write(json.dumps(data).encode())

            def do_GET(self):
                mock, _, _, key = self.path.strip("/").split("/")
                value = state[mock].get(key)
                self.reply(200 if value else 404, value)

            def do_POST(self):
                mock, path = self.path.lstrip("/").split("/", 1)
                data = self.rfile.read(int(self.headers["Content-Length"]))
                if path == "__admin/mappings" or self.command == "PUT":
                    mapping = json.loads(data)
                    state[mock][mapping["id"]] = mapping
                    self.reply(201 if self.command == "POST" else 200, mapping)
                    return
                mapping = next(m for m in state[mock].values() if m["request"]["urlPath"] == "/" + path)
                time.sleep(mapping["response"]["fixedDelayMilliseconds"] / 1000)
                self.reply(200)

            do_PUT = do_POST

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            customer = self.raw["customers"]["2342342"]
            customer.update(endpoint_scope="customer", ProductClasses={}, delay_ms=20)
            customer.pop("allowed_delays_ms")
            self.raw["customers"] = {"2342342": customer}
            self.raw["customer_groups"] = {}
            self.raw["wiremocks"] = {name: {"api": f"http://127.0.0.1:{server.server_port}/{name}",
                "prefix_handling": "strip", "customers": {"2342342": settings}}
                for name, settings in (("mock-1", {}), ("mock-2", {"delay_ms": 60}))}
            self.load()
            for flags in ([], ["--delay", "0"]):
                with contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(main(["apply", "-f", str(self.path), "--all-customers", "--all-mocks", *flags]), 0)
                    self.assertEqual(main(["verify", "-f", str(self.path), "--all-customers", *flags]), 0)
                self.assertIn("2 passed, 0 failed", output.getvalue())
                actual = [next(iter(state[name].values()))["response"]["fixedDelayMilliseconds"] for name in state]
                self.assertEqual(actual, [0, 0] if flags else [20, 60])
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                # The CLI override must be repeated; file expectations must not adopt live zeros.
                self.assertEqual(main(["verify", "-f", str(self.path), "--all-customers"]), 1)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
