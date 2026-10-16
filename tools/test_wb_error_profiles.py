"""Verify repeatable error selection, explicit restoration and preflight rejection."""

import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

from wiremock_benchmark_cli.cli import main
from wiremock_benchmark_cli.config import ConfigError, load_config
from wiremock_benchmark_cli.plan import make_plans


ROOT = Path(__file__).resolve().parents[1]
CODE = "2342342"


class ErrorProfilesTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "profile.yaml"
        self.report = Path(temporary.name) / "report.json"
        self.raw = yaml.safe_load((ROOT / "wb.yaml").read_text())

    def write(self):
        self.path.write_text(yaml.safe_dump(self.raw))

    def plan(self, **options):
        self.write()
        return make_plans(load_config(self.path), all_mocks=True, customer=CODE, **options)

    def test_file_precedence_and_cli_none_restore_keep_mapping_identities(self):
        normal = self.plan()
        self.raw["customers"][CODE]["error_profile"] = "server-error"
        self.raw["wiremocks"]["mock-2"]["customers"][CODE]["error_profile"] = "none"
        self.raw["wiremocks"]["mock-3"]["customers"][CODE]["error_profile"] = "timeout"
        plan = self.plan()
        for index, target in enumerate(plan["targets"]):
            name, source, status, delay = (
                ("none", "mock-customer", 200, 6000) if index == 1 else
                ("timeout", "mock-customer", 200, 60000) if index == 2 else
                ("server-error", "customer", 500, 1000))
            for resolution, mapping in zip(target["resolved_profiles"], target["mappings"]):
                self.assertEqual((resolution["error_profile"], resolution["error_profile_source"]), (name, source))
                self.assertEqual(mapping["response"]["status"], status)
                self.assertEqual(mapping["response"]["fixedDelayMilliseconds"], delay)
            self.assertEqual([m["id"] for m in target["mappings"]],
                             [m["id"] for m in normal["targets"][index]["mappings"]])
        restored = self.plan(profile="none")
        self.assertEqual([t["mappings"] for t in restored["targets"]],
                         [t["mappings"] for t in normal["targets"]])
        self.assertTrue(all(r["error_profile_source"] == "cli" for t in restored["targets"] for r in t["resolved_profiles"]))
        overridden = self.plan(profile="server-error", delay=0)
        self.assertTrue(all(m["response"]["status"] == 500 and m["response"]["fixedDelayMilliseconds"] == 0
                            for t in overridden["targets"] for m in t["mappings"]))

    def test_file_timeout_conflicts_with_cli_delay_before_any_http(self):
        self.raw["wiremocks"]["mock-5"]["customers"][CODE]["error_profile"] = "timeout"
        self.write()
        for command in ("apply", "verify"):
            with self.subTest(command=command), patch("wiremock_benchmark_cli.api.WireMockAdmin.request") as http:
                with contextlib.redirect_stderr(io.StringIO()) as error:
                    code = main([command, "-f", str(self.path), "--all-mocks", "--customer", CODE, "--delay", "0"])
                self.assertEqual(code, 2)
                self.assertIn("omit --delay", error.getvalue())
                http.assert_not_called()
        plan = self.plan(delay=0, profile="none")
        self.assertTrue(all(m["response"]["fixedDelayMilliseconds"] == 0
                            for t in plan["targets"] for m in t["mappings"]))
        # An unselected mock's timeout does not veto a normal selected mock.
        single = make_plans(load_config(self.path), mock="mock-1", customer=CODE, delay=0)
        self.assertEqual(single["targets"][0]["mappings"][0]["response"]["fixedDelayMilliseconds"], 0)

    def test_omitted_customer_profile_defaults_to_none_and_can_be_overridden(self):
        explicit = self.plan()
        self.raw["customers"][CODE].pop("error_profile")
        omitted = self.plan()
        self.assertEqual([t["mappings"] for t in omitted["targets"]],
                         [t["mappings"] for t in explicit["targets"]])
        self.assertTrue(all(r["error_profile"] == "none" and r["error_profile_source"] == "default"
                            for t in omitted["targets"] for r in t["resolved_profiles"]))
        self.raw["wiremocks"]["mock-2"]["customers"][CODE]["error_profile"] = "server-error"
        override = self.plan()["targets"][1]
        self.assertTrue(all(r["error_profile"] == "server-error" and r["error_profile_source"] == "mock-customer"
                            for r in override["resolved_profiles"]))
        cli = self.plan(profile="none")
        self.assertTrue(all(r["error_profile"] == "none" and r["error_profile_source"] == "cli"
                            for t in cli["targets"] for r in t["resolved_profiles"]))

    def test_invalid_and_unknown_selections_fail_including_unselected_targets(self):
        original = copy.deepcopy(self.raw)
        mutations = [lambda c: c["error_profiles"].update(none=c["error_profiles"]["server-error"]),
                     lambda c: c["customers"][CODE]["ProductClasses"].update(Productclass={"error_profile": "none"})]
        for value in (None, "", True, 1, [], {}, "unknown", " NONE "):
            mutations.extend([
                lambda c, v=value: c["customers"][CODE].update(error_profile=v),
                lambda c, v=value: c["wiremocks"]["mock-5"]["customers"][CODE].update(error_profile=v)])
        for mutate in mutations:
            self.raw = copy.deepcopy(original)
            mutate(self.raw)
            self.write()
            with self.subTest(config=self.raw), patch("wiremock_benchmark_cli.api.WireMockAdmin.request") as http:
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(main(["apply", "-f", str(self.path), "--mock", "mock-1",
                                           "--customer", "3243423434", "--error-profile", "none"]), 2)
                http.assert_not_called()

    def test_list_and_dry_run_reports_share_file_selection_and_provenance(self):
        self.raw["customers"][CODE]["error_profile"] = "server-error"
        self.raw["wiremocks"]["mock-2"]["customers"][CODE]["error_profile"] = "timeout"
        self.write()
        for command, flags in (("list", []), ("apply", ["--dry-run"])):
            with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main([command, "-f", str(self.path), "--all-mocks", "--customer", CODE,
                                       "--output", str(self.report), "--overwrite-output", *flags]), 0)
            report = json.loads(self.report.read_text())
            target = report["resolved"]["targets"][1]
            resolutions = target["endpoints" if command == "list" else "resolved_profiles"]
            self.assertTrue(all(r["error_profile"] == "timeout" and r["error_profile_source"] == "mock-customer"
                                and r["delay_ms"] == 60000 for r in resolutions))
            if command == "list":
                self.assertIn("error_profile=server-error (customer)", out.getvalue())
                self.assertIn("error_profile=timeout (mock-customer)", out.getvalue())

    def test_none_is_valid_without_error_definitions_and_unknown_cli_name_fails(self):
        self.raw["error_profiles"] = {}
        plan = self.plan(profile="none")
        self.assertTrue(all(m["response"]["status"] == 200 for t in plan["targets"] for m in t["mappings"]))
        with self.assertRaises(ConfigError):
            self.plan(profile="unknown")


if __name__ == "__main__":
    unittest.main()
