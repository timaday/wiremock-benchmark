"""Exercise named targets and groups through an isolated five-mock Nginx ingress.

Set WB_INTEGRATION_FIVE_BASE to its public root URL. Adds unique test customers;
retains all mappings, including unrelated mappings already on the targets.
"""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from urllib.request import Request, urlopen
import uuid

import yaml


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get("WB_INTEGRATION_FIVE_BASE"), "Set WB_INTEGRATION_FIVE_BASE to an isolated five-mock ingress")
class NamedTargetsSmoke(unittest.TestCase):
    def test_five_mock_assignments_and_group_updates(self):
        base = os.environ["WB_INTEGRATION_FIVE_BASE"].rstrip("/")
        config = yaml.safe_load((ROOT / "wb.yaml").read_text())
        suffix = uuid.uuid4().hex[:10]
        a, b, c, d = [letter + "-" + suffix for letter in "abcd"]
        config["customers"] = {code: dict(name="Test Customer " + code, response_profile="accepted", delay=[0, 1000, 6000],
                                          ProductClasses={"Product": None}) for code in (a, b, c, d)}
        config["customer_groups"] = {"selected": [a, c], "all": [a, b, c, d]}
        assignments = [[a, b], [b, c], [c], [a], [d]]
        for index, members in enumerate(assignments, 1):
            config["wiremocks"][f"mock-{index}"] = dict(api=f"{base}/mock-{index}",
                                                        prefix_handling="strip", customers=members)

        def mappings(target):
            with urlopen(config["wiremocks"][target]["api"] + "/__admin/mappings", timeout=5) as response:
                return json.load(response)["mappings"]

        before = {name: mappings(name) for name in config["wiremocks"]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wb.yaml"
            path.write_text(yaml.safe_dump(config, sort_keys=False))

            def cli(*arguments, status=0):
                result = subprocess.run([str(ROOT / "wb"), "--config", str(path), *arguments],
                                        capture_output=True, text=True, timeout=40)
                self.assertEqual(result.returncode, status, result.stdout + result.stderr)
                return result

            cli("--all-mocks", "--all-customers", "--delay", "0")
            plan = json.loads(cli("--all-mocks", "--all-customers", "--delay", "0", "--dry-run").stdout)
            for target in plan["targets"]:
                actual = mappings(target["mock"])
                self.assertEqual(len(actual), len(before[target["mock"]]) + len(target["customers"]))
                for old in before[target["mock"]]:
                    self.assertIn(old, actual)
                for mapping in target["mappings"]:
                    with urlopen(Request(target["wiremock_api"] + mapping["request"]["urlPath"],
                                         method="POST", data=b"{}"), timeout=5) as response:
                        self.assertEqual(response.status, 200)
                        self.assertEqual(json.load(response), config["response_profiles"]["accepted"]["jsonBody"])

            skipped_before = mappings("mock-5")
            result = cli("--all-mocks", "--group", "selected", "--delay", "1000")
            self.assertIn("WARNING [mock-5]", result.stderr)
            self.assertIn("[mock-5] No matching assigned customers", result.stdout)
            self.assertEqual(mappings("mock-5"), skipped_before)
            for target in plan["targets"]:
                actual = {mapping["id"]: mapping for mapping in mappings(target["mock"])}
                for expected in target["mappings"]:
                    code = expected["metadata"]["wb"]["customer"]
                    self.assertEqual(actual[expected["id"]]["response"]["fixedDelayMilliseconds"],
                                     1000 if code in (a, c) else 0)
            cli("--all-mocks", "--group", "selected", "--delay", "1000")
            snapshot = {name: mappings(name) for name in config["wiremocks"]}
            for target in plan["targets"]:
                self.assertEqual(len(snapshot[target["mock"]]), len(before[target["mock"]]) + len(target["customers"]))

            cli("--mock", "mock-2", "--customer", b, "--delay", "6000")
            for name in config["wiremocks"]:
                if name != "mock-2":
                    self.assertEqual(mappings(name), snapshot[name])
            changed = [m for m in mappings("mock-2") if m.get("metadata", {}).get("wb", {}).get("customer") == b]
            self.assertEqual(len(changed), 1)
            self.assertEqual(changed[0]["response"]["fixedDelayMilliseconds"], 6000)
            snapshot = {name: mappings(name) for name in config["wiremocks"]}
            result = cli("--mock", "mock-5", "--group", "selected", "--delay", "1000", status=2)
            self.assertIn("not assigned", result.stderr)
            self.assertEqual({name: mappings(name) for name in config["wiremocks"]}, snapshot)
            print("verified: five independent mocks, disjoint/overlapping assignments, group routing, "
                  "explicit no-match warning, single-target isolation, idempotence, rejected unassigned group")


if __name__ == "__main__":
    unittest.main(verbosity=2)
