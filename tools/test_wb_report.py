"""Exercise report evidence against HTTP effects, partial failures and file safety."""

import contextlib
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import yaml

from wiremock_benchmark_cli.cli import main


ROOT = Path(__file__).resolve().parents[1]


class ReportTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config = self.root / "profile.yaml"
        self.output = self.root / "report.json"
        self.mappings = {}
        self.calls = []
        self.public_calls = []
        self.mutations = 0
        self.fail_operation = None
        self.fail_read = False
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def handle_request(self):
                owner.calls.append((self.command, self.path))
                route = self.path.removeprefix("/mock-1")
                prefix = "/__admin/mappings"
                status, payload = 200, None
                public_response = None
                if route.startswith(prefix):
                    identifier = route.removeprefix(prefix).lstrip("/")
                    if self.command == "GET":
                        if owner.fail_read:
                            status = 503
                        elif not identifier:
                            payload = {"mappings": list(owner.mappings.values()),
                                       "meta": {"total": len(owner.mappings)}}
                        else:
                            payload = owner.mappings.get(identifier)
                            status = 200 if payload is not None else 404
                    else:
                        owner.mutations += 1
                        if owner.fail_operation == self.command and owner.mutations == 2:
                            status = 503
                        elif self.command == "DELETE":
                            owner.mappings.pop(identifier, None)
                        else:
                            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                            owner.mappings[payload["id"]] = payload
                else:
                    body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                    owner.public_calls.append((self.command, route, body, self.headers.get("Content-Type")))
                    matched = next((m for m in owner.mappings.values() if m["request"]["urlPath"] == route
                                    and m["request"]["method"] == self.command), None)
                    if matched is None:
                        status = 404
                    else:
                        public_response = matched["response"]
                        status = public_response["status"]
                        time.sleep(public_response["fixedDelayMilliseconds"] / 1000)
                data = json.dumps(payload).encode() if payload is not None else b""
                if public_response is not None:
                    data = (json.dumps(public_response["jsonBody"]).encode() if "jsonBody" in public_response
                            else public_response["body"].encode())
                self.send_response(status)
                if payload is not None:
                    self.send_header("Content-Type", "application/json")
                for key, value in (public_response["headers"].items() if public_response is not None else []):
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(data)

            do_GET = do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = handle_request

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        raw = yaml.safe_load((ROOT / "wb.yaml").read_text())
        raw["wiremocks"] = {"mock-1": {"api": f"http://127.0.0.1:{server.server_port}/mock-1",
                                       "prefix_handling": "strip", "customers": {"2342342": {}}}}
        customer = raw["customers"]["2342342"]
        customer["delay_ms"] = 0
        customer["ProductClasses"] = {"One": None, "Two": None}
        self.config.write_text(yaml.safe_dump(raw))

    def invoke(self, command, *extra, output=True):
        args = [command] if command else []
        args += ["-f", str(self.config), "--mock", "mock-1", "--customer", "2342342"]
        if output:
            args += ["--output", str(self.output)]
        args += list(extra)
        with contextlib.redirect_stdout(io.StringIO()) as stdout, contextlib.redirect_stderr(io.StringIO()) as stderr:
            code = main(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def report(self):
        return json.loads(self.output.read_text())

    def test_all_commands_record_actual_results_and_preserve_console_output(self):
        code, stdout, _ = self.invoke("apply")
        self.assertEqual(code, 0)
        self.assertIn("Applied and verified 2", stdout)
        report = self.report()
        self.assertEqual(report["report_version"], 1)
        self.assertEqual(report["summary"], {"verified": 2})
        self.assertEqual(report["config"]["sha256"], hashlib.sha256(self.config.read_bytes()).hexdigest())
        self.assertEqual(report["config"]["path"], str(self.config))
        self.assertLessEqual(report["started_at"], report["finished_at"])
        self.assertEqual({e["mapping_id"] for e in report["events"] if e["status"] == "verified"}, set(self.mappings))
        for command in ("list", "verify", "clean"):
            with self.subTest(command=command):
                before = len(self.calls)
                code, stdout, _ = self.invoke(command, "--overwrite-output")
                self.assertEqual(code, 0)
                report = self.report()
                self.assertEqual(report["command"], command)
                self.assertEqual(report["status"], "success")
                self.assertTrue(stdout)
                if command == "list":
                    self.assertEqual(report["summary"]["endpoints"], 2)
                    self.assertEqual(len(self.calls), before)
                elif command == "verify":
                    self.assertEqual(report["summary"], {"passed": 2, "failed": 0})
                    self.assertTrue(all(e["passed"] for e in report["events"]))
                else:
                    self.assertEqual(report["summary"], {"candidates": 2, "deleted": 0, "absent": 0, "mode": "preview"})
                    self.assertEqual(len(self.mappings), 2)
        self.assertEqual(self.invoke("clean", "--execute", "--overwrite-output")[0], 0)
        self.assertEqual(self.report()["summary"]["deleted"], 2)
        self.assertFalse(self.mappings)
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o600)

    def test_default_apply_dry_run_records_overrides_without_http(self):
        self.assertEqual(self.invoke("", "--dry-run", "--delay", "1000")[0], 0)
        report = self.report()
        self.assertEqual(report["command"], "apply")
        self.assertEqual(report["options"]["delay"], 1000)
        self.assertTrue(all(e["delay_ms"] == 1000 and e["delay_source"] == "cli"
                            for e in report["resolved"]["targets"][0]["resolved_profiles"]))
        self.assertFalse(report["summary"]["live_state_checked"])
        self.assertFalse(self.calls)

    def test_named_request_profiles_apply_list_verify_and_report_over_http(self):
        raw = yaml.safe_load(self.config.read_text())
        raw["request_profiles"] = {
            "submit": {"method": "POST", "probe_body": {"type": "json", "value": {"correlationId": "check"}}},
            "read": {"method": "GET", "probe_body": {"type": "none"}},
            "head": {"method": "HEAD", "probe_body": {"type": "none"}},
            "text": {"method": "PUT", "probe_body": {"type": "text", "value": "café\n"}}}
        customer = raw["customers"]["2342342"]
        customer.update(request_profile="submit", ProductClasses={
            "Inherited": None, "Read": {"request_profile": "read"},
            "Head": {"request_profile": "head", "response_profile": "accepted"},
            "Text": {"request_profile": "text"}})
        self.config.write_text(yaml.safe_dump(raw))
        self.assertEqual(self.invoke("apply")[0], 0)
        identities = set(self.mappings)
        self.assertEqual(self.invoke("list", "--overwrite-output")[0], 0)
        listed = self.report()["resolved"]["targets"][0]["endpoints"]
        self.assertEqual({r["method"] for r in listed}, {"POST", "GET", "HEAD", "PUT"})
        self.assertEqual(self.invoke("verify", "--overwrite-output")[0], 0)
        report = self.report()
        self.assertEqual(report["summary"], {"passed": 4, "failed": 0})
        by_method = {method: (body, content_type) for method, _, body, content_type in self.public_calls}
        self.assertEqual(by_method["GET"], (b"", None))
        self.assertEqual(by_method["HEAD"], (b"", None))
        self.assertEqual(by_method["PUT"], ("café\n".encode(), "text/plain; charset=utf-8"))
        self.assertEqual(json.loads(by_method["POST"][0]), {"correlationId": "check"})
        self.assertEqual(by_method["POST"][1], "application/json")
        self.assertTrue(all(set(m["request"]) == {"method", "urlPath"} for m in self.mappings.values()))
        # Change the inherited method and body: apply updates the same owned ID.
        customer["request_profile"] = "read"
        self.config.write_text(yaml.safe_dump(raw))
        self.assertEqual(self.invoke("verify", "--overwrite-output")[0], 1)
        self.assertEqual(self.invoke("apply", "--overwrite-output")[0], 0)
        self.assertEqual(set(self.mappings), identities)
        self.assertEqual(self.invoke("verify", "--overwrite-output")[0], 0)

    def test_response_request_default_is_used_for_normal_and_error_http_probes(self):
        raw = yaml.safe_load(self.config.read_text())
        raw["request_profiles"] = {"update": {"method": "PUT", "probe_body": {"type": "text", "value": "request from response"}}}
        raw["response_profiles"]["empty-ok"]["request_profile"] = "update"
        raw["error_profiles"]["timeout"]["delay_ms"] = 20
        for error_profile in ("none", "server-error", "timeout"):
            with self.subTest(error_profile=error_profile):
                raw["customers"]["2342342"]["error_profile"] = error_profile
                self.config.write_text(yaml.safe_dump(raw))
                self.public_calls.clear()
                self.assertEqual(self.invoke("apply", "--overwrite-output")[0], 0)
                self.assertTrue(all("request_profile" not in m["response"] for m in self.mappings.values()))
                self.assertEqual(self.invoke("list", "--overwrite-output")[0], 0)
                self.assertTrue(all(r["request_profile_source"] == "response-profile"
                                    for r in self.report()["resolved"]["targets"][0]["endpoints"]))
                self.assertEqual(self.invoke("verify", "--overwrite-output")[0], 0)
                report = self.report()
                self.assertEqual(report["summary"], {"passed": 2, "failed": 0})
                self.assertTrue(all(r["request_profile"] == "update" and r["request_profile_source"] == "response-profile"
                                    for r in report["resolved"]["targets"][0]["resolved_profiles"]))
                self.assertEqual(len(self.public_calls), 2)
                self.assertTrue(all(method == "PUT" and body == b"request from response"
                                    and content_type == "text/plain; charset=utf-8"
                                    for method, _, body, content_type in self.public_calls))

    def test_file_error_profiles_apply_verify_and_restore_over_http(self):
        raw = yaml.safe_load(self.config.read_text())
        raw["customers"]["2342342"].pop("error_profile")
        self.config.write_text(yaml.safe_dump(raw))
        self.assertEqual(self.invoke("apply")[0], 0)
        self.assertEqual(self.invoke("verify", "--overwrite-output")[0], 0)
        self.assertTrue(all(r["error_profile"] == "none" and r["error_profile_source"] == "default"
                            for r in self.report()["resolved"]["targets"][0]["resolved_profiles"]))
        raw["customers"]["2342342"]["error_profile"] = "server-error"
        raw["error_profiles"]["timeout"]["delay_ms"] = 40
        self.config.write_text(yaml.safe_dump(raw))
        original_ids = None
        for selection, expected_status, expected_delay in ((None, 500, 0), ("timeout", 200, 40), ("none", 200, 0)):
            if selection is not None:
                raw["wiremocks"]["mock-1"]["customers"]["2342342"]["error_profile"] = selection
            self.config.write_text(yaml.safe_dump(raw))
            with self.subTest(selection=selection):
                self.assertEqual(self.invoke("apply", "--overwrite-output")[0], 0)
                if original_ids is None:
                    original_ids = set(self.mappings)
                self.assertEqual(set(self.mappings), original_ids)
                self.assertTrue(all(m["response"]["status"] == expected_status
                                    and m["response"]["fixedDelayMilliseconds"] == expected_delay
                                    for m in self.mappings.values()))
                self.assertEqual(self.invoke("verify", "--overwrite-output")[0], 0)
                report = self.report()
                self.assertEqual(report["summary"], {"passed": 2, "failed": 0})
                self.assertTrue(all(r["error_profile_source"] == ("customer" if selection is None else "mock-customer")
                                    for r in report["resolved"]["targets"][0]["resolved_profiles"]))
        # CLI overrides are explicit and must be repeated when verifying.
        raw["wiremocks"]["mock-1"]["customers"]["2342342"]["error_profile"] = "server-error"
        self.config.write_text(yaml.safe_dump(raw))
        self.assertEqual(self.invoke("apply", "--error-profile", "none", "--overwrite-output")[0], 0)
        self.assertEqual(self.invoke("verify", "--overwrite-output")[0], 1)
        self.assertEqual(self.invoke("verify", "--error-profile", "none", "--overwrite-output")[0], 0)
        self.assertTrue(all(r["error_profile"] == "none" and r["error_profile_source"] == "cli"
                            for r in self.report()["resolved"]["targets"][0]["resolved_profiles"]))

    def test_partial_apply_records_attempted_and_verified_writes(self):
        self.fail_operation = "POST"
        self.assertEqual(self.invoke("apply")[0], 1)
        report = self.report()
        self.assertEqual(report["status"], "failed")
        self.assertEqual(len(self.mappings), 1)
        events = report["events"]
        self.assertEqual(sum(e["status"] == "attempted" for e in events), 2)
        self.assertEqual(sum(e["status"] == "verified" for e in events), 1)
        self.assertEqual(events[-1]["verified"], 1)
        self.assertIn("HTTP 503", report["errors"][0])

    def test_preflight_failure_has_no_mutation_attempt(self):
        self.fail_read = True
        self.assertEqual(self.invoke("apply")[0], 1)
        self.assertEqual(self.mutations, 0)
        self.assertFalse(any(e["status"] == "attempted" for e in self.report()["events"]))

    def test_partial_cleanup_keeps_verified_deletion_and_failure(self):
        self.assertEqual(self.invoke("apply", output=False)[0], 0)
        self.mutations = 0
        self.fail_operation = "DELETE"
        self.assertEqual(self.invoke("clean", "--execute")[0], 1)
        report = self.report()
        self.assertEqual(len(self.mappings), 1)
        self.assertEqual(report["events"][-1]["deleted"], 1)
        self.assertEqual(report["events"][-1]["attempted"], 2)
        self.assertTrue(report["errors"])

    def test_verification_failure_is_reported_per_endpoint(self):
        self.assertEqual(self.invoke("verify")[0], 1)
        report = self.report()
        self.assertEqual(report["summary"], {"passed": 0, "failed": 2})
        self.assertTrue(all(not e["passed"] and "HTTP 404" in e["detail"] for e in report["events"]))
        self.assertEqual(self.mutations, 0)

    def test_invalid_yaml_is_reported_by_every_command(self):
        self.config.write_bytes(b"schema_version: 99\r\n")
        for command in ("apply", "list", "verify", "clean"):
            with self.subTest(command=command):
                self.assertEqual(self.invoke(command, "--overwrite-output")[0], 2)
                report = self.report()
                self.assertEqual(report["status"], "failed")
                self.assertEqual(report["config"]["sha256"], hashlib.sha256(self.config.read_bytes()).hexdigest())
                self.assertIsNone(report["resolved"])
                self.assertTrue(report["errors"])
        self.assertFalse(self.calls)

    def test_existing_output_refused_before_http_unless_explicitly_replaced(self):
        self.output.write_text("preserve me")
        for command in ("apply", "list", "verify", "clean"):
            self.assertEqual(self.invoke(command)[0], 2)
        self.assertFalse(self.calls)
        self.assertEqual(self.output.read_text(), "preserve me")
        self.assertEqual(self.invoke("list", "--overwrite-output")[0], 0)
        self.assertEqual(self.report()["status"], "success")

    def test_invalid_destinations_and_input_alias_are_refused(self):
        original = self.config.read_bytes()
        for destination in (self.root / "missing" / "report.json", self.root, self.config):
            self.output = destination
            self.assertEqual(self.invoke("apply", "--overwrite-output")[0], 2)
        self.output = self.root / "alias"
        self.output.hardlink_to(self.config)
        self.assertEqual(self.invoke("apply", "--overwrite-output")[0], 2)
        self.assertEqual(self.config.read_bytes(), original)
        self.assertFalse(self.calls)
        self.assertEqual(self.invoke("apply", "--overwrite-output", output=False)[0], 2)

    def test_late_report_failure_does_not_claim_to_undo_writes(self):
        with patch("wiremock_benchmark_cli.report.os.link", side_effect=OSError("private detail")):
            code, _, error = self.invoke("apply")
        self.assertEqual(code, 1)
        self.assertEqual(len(self.mappings), 2)
        self.assertIn("remain in effect", error)
        self.assertNotIn("private detail", error)
        self.assertFalse(self.output.exists())
        self.assertFalse(list(self.root.glob(".wb-report-*")))

    def test_interruption_saves_completed_evidence(self):
        with patch("wiremock_benchmark_cli.api.WireMockAdmin.request", side_effect=KeyboardInterrupt):
            self.assertEqual(self.invoke("apply")[0], 130)
        self.assertEqual(self.report()["status"], "interrupted")
        self.assertEqual(self.report()["events"][0]["status"], "started")
        self.assertTrue(self.report()["errors"])

    def test_output_created_during_run_is_not_overwritten(self):
        link = os.link

        def competing_output(source, destination):
            Path(destination).write_text("created by another invocation")
            link(source, destination)

        with patch("wiremock_benchmark_cli.report.os.link", side_effect=competing_output):
            code, _, error = self.invoke("apply")
        self.assertEqual(code, 1)
        self.assertEqual(self.output.read_text(), "created by another invocation")
        self.assertEqual(len(self.mappings), 2)
        self.assertIn("remain in effect", error)

    def test_missing_dependency_report_matches_process_exit_code(self):
        result = subprocess.run([sys.executable, "-S", str(ROOT / "wb"), "list",
                                 "-f", str(self.config), "--all-customers", "--output", str(self.output)],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 2)
        report = self.report()
        self.assertEqual(report["exit_code"], result.returncode)
        self.assertIn("PyYAML", report["errors"][0])
        self.assertIsNone(report["config"])

    def test_help_and_syntax_errors_do_not_write_reports(self):
        for command in ("apply", "list", "verify", "clean"):
            for args, expected in ((["--help"], 0), (["--unknown-option"], 2)):
                with self.subTest(command=command, args=args), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as stopped:
                        main([command, "--output", str(self.output), *args])
                    self.assertEqual(stopped.exception.code, expected)
                self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
