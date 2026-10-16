"""Verify cleanup over the admin HTTP interface without touching user mappings."""

import contextlib
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
import uuid

import yaml

from wiremock_benchmark_cli.api import AdminError
from wiremock_benchmark_cli.clean import clean_targets
from wiremock_benchmark_cli.cli import main
from wiremock_benchmark_cli.config import load_config
from wiremock_benchmark_cli.identity import mapping_id, mapping_metadata, owned_customer


ROOT = Path(__file__).resolve().parents[1]


def owned(code, product, extension=""):
    return {"id": mapping_id(code, product, extension), "metadata": mapping_metadata(code, product, extension),
            "request": {"method": "POST", "urlPath": "/fixture"},
            "response": {"status": 200, "body": ""}}


class OwnershipTest(unittest.TestCase):
    def test_recognizes_both_identities_and_rejects_lookalikes(self):
        for product in ("Product", None):
            mapping = owned("00123", product)
            self.assertEqual(owned_customer(mapping), "00123")
            for mutate in (
                lambda m: m.update(id=str(uuid.uuid4())),
                lambda m: m["metadata"]["wb"].update(version=2),
                lambda m: m["metadata"]["wb"].update(version=True),
                lambda m: m["metadata"]["wb"].update(customer=123),
                lambda m: m["metadata"].update(other="owner"),
                lambda m: m["metadata"]["wb"].update(extra="unknown"),
            ):
                altered = copy.deepcopy(mapping)
                mutate(altered)
                self.assertIsNone(owned_customer(altered))
        self.assertIsNone(owned_customer({"id": str(uuid.uuid4()), "name": "wb: pretend"}))
        self.assertIsNone(owned_customer({"metadata": {"wb": None}}))


class CleanHttpTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.fail_target = None
        self.incomplete = False
        self.before_read = None
        self.delete_mode = "normal"
        self.current = owned("2342342", "Current")
        self.stale = owned("2342342", "Removed")
        self.shared = owned("2342342", None)
        self.other = owned("removed-customer", "Old")
        self.manual = {"id": str(uuid.uuid4()), "name": "wb: manual", "request": {"urlPath": "/manual"}}
        self.forged = owned("2342342", "Lookalike")
        self.forged["id"] = str(uuid.uuid4())
        self.state = {"one": {m["id"]: copy.deepcopy(m) for m in
                              (self.current, self.stale, self.shared, self.other, self.manual, self.forged)}, "two": {}}
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def reply(self, status, body=None):
                self.send_response(status)
                self.end_headers()
                if body is not None:
                    self.wfile.write(json.dumps(body).encode())

            def do_GET(self):
                owner.calls.append(("GET", self.path))
                target, *parts = self.path.strip("/").split("/")
                if target == owner.fail_target:
                    self.reply(503)
                elif parts == ["__admin", "mappings"]:
                    values = list(owner.state[target].values())
                    self.reply(200, {"mappings": values, "meta": {"total": len(values) + int(owner.incomplete)}})
                elif len(parts) == 3 and parts[:2] == ["__admin", "mappings"]:
                    if owner.before_read:
                        owner.before_read(target, parts[-1])
                    value = owner.state[target].get(parts[-1])
                    self.reply(200 if value else 404, value)
                else:
                    self.reply(404)

            def do_DELETE(self):
                owner.calls.append(("DELETE", self.path))
                target, _, _, key = self.path.strip("/").split("/")
                if owner.delete_mode == "fail":
                    self.reply(503)
                    return
                if owner.delete_mode != "retain":
                    owner.state[target].pop(key, None)
                self.reply(200)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.targets = [{"mock": name, "api": self.base + "/" + name,
                         "desired_ids": {self.current["id"]}} for name in ("one", "two")]

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def clean(self, customer="2342342", stale=True, execute=False):
        self.output = []
        return clean_targets(self.targets, customer, stale, execute, 2, self.output.append)

    def test_preview_is_get_only_and_preserves_every_mapping(self):
        before = copy.deepcopy(self.state)
        result = self.clean()
        self.assertEqual(result, {"candidates": 2, "deleted": 0, "absent": 0})
        self.assertEqual(before, self.state)
        self.assertEqual(self.calls, [("GET", "/one/__admin/mappings"), ("GET", "/two/__admin/mappings")])
        self.assertTrue(any("Preserved 2" in line for line in self.output))

    def test_execute_stale_removes_only_owned_stale_and_verifies_absence(self):
        result = self.clean(execute=True)
        self.assertEqual(result["deleted"], 2)
        self.assertEqual(set(self.state["one"]), {m["id"] for m in (self.current, self.other, self.manual, self.forged)})
        for key in (self.stale["id"], self.shared["id"]):
            index = self.calls.index(("DELETE", "/one/__admin/mappings/" + key))
            self.assertEqual(self.calls[index - 1], ("GET", "/one/__admin/mappings/" + key))
            self.assertEqual(self.calls[index + 1], ("GET", "/one/__admin/mappings/" + key))

    def test_all_owned_and_removed_customer_selection(self):
        self.assertEqual(self.clean(stale=False)["candidates"], 3)
        self.assertEqual(self.clean(customer=None, stale=False)["candidates"], 4)
        self.assertEqual(self.clean(customer="removed-customer", execute=True)["deleted"], 1)
        self.assertIn(self.current["id"], self.state["one"])

    def test_stale_shared_extension_is_deleted_and_desired_extension_preserved(self):
        old = owned("extension-customer", None, "old/v1")
        desired = owned("extension-customer", None, "transactions")
        self.state["one"].update({m["id"]: m for m in (old, desired)})
        self.targets[0]["desired_ids"].add(desired["id"])
        result = self.clean(customer="extension-customer", execute=True)
        self.assertEqual(result["deleted"], 1)
        self.assertNotIn(old["id"], self.state["one"])
        self.assertIn(desired["id"], self.state["one"])

    def test_second_target_failure_prevents_all_deletes(self):
        self.fail_target = "two"
        with self.assertRaisesRegex(AdminError, "No DELETE requests attempted"):
            self.clean(execute=True)
        self.assertFalse(any(method == "DELETE" for method, _ in self.calls))

    def test_incomplete_list_prevents_deletion(self):
        self.incomplete = True
        with self.assertRaisesRegex(AdminError, "incomplete"):
            self.clean(execute=True)
        self.assertFalse(any(method == "DELETE" for method, _ in self.calls))

    def test_changed_mapping_is_not_deleted(self):
        def mutate(target, key):
            self.state[target][key]["response"]["status"] = 503
        self.before_read = mutate
        with self.assertRaisesRegex(AdminError, "changed since discovery"):
            self.clean(execute=True)
        self.assertFalse(any(method == "DELETE" for method, _ in self.calls))

    def test_already_absent_is_reported_without_delete(self):
        self.before_read = lambda target, key: self.state[target].pop(key, None)
        self.assertEqual(self.clean(execute=True), {"candidates": 2, "deleted": 0, "absent": 2})
        self.assertFalse(any(method == "DELETE" for method, _ in self.calls))

    def test_failed_delete_and_failed_postcondition_stop_cleanup(self):
        for mode, error in (("fail", "HTTP 503"), ("retain", "still exists")):
            self.calls.clear()
            self.delete_mode = mode
            with self.subTest(mode=mode), self.assertRaisesRegex(AdminError, error) as caught:
                self.clean(execute=True)
            self.assertIn("Verified deletions=0", str(caught.exception))
            self.assertEqual(sum(method == "DELETE" for method, _ in self.calls), 1)

    def test_cli_resolves_stale_assignments_and_explicit_dry_run(self):
        config = load_config(ROOT / "wb.yaml")
        config["wiremocks"] = {"one": {"api": self.base + "/one", "prefix_handling": "strip", "customers": {"3243423434": {}}}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "phase.yaml"
            path.write_text(yaml.safe_dump(config))
            args = ["clean", "-f", str(path), "--mock", "one", "--customer", "2342342", "--stale-only"]
            for flags in ([], ["--dry-run"]):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(main([*args, *flags]), 0)
                self.assertIn("Preview: 3 mapping(s)", output.getvalue())
            self.assertFalse(any(method == "DELETE" for method, _ in self.calls))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main([*args, "--execute"]), 0)
            self.assertEqual(set(self.state["one"]), {m["id"] for m in (self.other, self.manual, self.forged)})

    def test_cli_rejects_invalid_scope_and_conflicting_modes_before_http(self):
        cases = [[], ["--mock", "one"], ["--all-customers"],
                 ["--all-mocks", "--all-customers", "--dry-run", "--execute"],
                 ["--all-mocks", "--all-customers", "--admin-timeout", "nan"]]
        for args in cases:
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                main(["clean", *args])
            self.assertEqual(caught.exception.code, 2)
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
