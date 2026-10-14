"""Qualify wb verify through an isolated five-mock public Nginx ingress.

The test installs and alters its own fixtures; verify itself must never alter
server mappings. Set WB_INTEGRATION_FIVE_BASE to the isolated ingress root.
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
class VerifyLiveSmoke(unittest.TestCase):
    def test_verifies_five_mocks_and_detects_installed_and_served_mismatches(self):
        base = os.environ["WB_INTEGRATION_FIVE_BASE"].rstrip("/")
        config = yaml.safe_load((ROOT / "wb.yaml").read_text())
        for index, target in enumerate(config["wiremocks"].values(), 1):
            target["api"] = f"{base}/mock-{index}"
        config["error_profiles"]["timeout"]["delay"] = 600

        def admin(mock, path="/__admin/mappings", method="GET", body=None):
            request = Request(config["wiremocks"][mock]["api"] + path, method=method,
                              data=json.dumps(body).encode() if body is not None else None,
                              headers={"Content-Type": "application/json"})
            with urlopen(request, timeout=5) as response:
                content = response.read()
                return json.loads(content) if content else None

        def snapshot():
            return {name: {m["id"]: m for m in admin(name)["mappings"]} for name in config["wiremocks"]}

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wb.yaml"
            path.write_text(yaml.safe_dump(config, sort_keys=False))

            def cli(command, *args, status=0):
                result = subprocess.run([str(ROOT / "wb"), *command, "--config", str(path), *args],
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, status, result.stdout + result.stderr)
                return result.stdout

            cli([], "--all-mocks", "--all-customers", "--delay", "0")
            before = snapshot()
            output = cli(["verify"], "--all-customers", "--delay", "0")
            self.assertIn("15 passed, 0 failed", output)
            self.assertEqual(snapshot(), before)
            output = cli(["verify"], "--customer", "2342342", "--delay", "0")
            self.assertIn("10 passed, 0 failed", output)

            output = cli(["verify"], "--mock", "mock-1", "--customer", "2342342", "--delay", "1000", status=1)
            self.assertIn("0 passed, 2 failed", output)
            self.assertIn("probe not sent", output)
            self.assertEqual(snapshot(), before)

            cli([], "--mock", "mock-2", "--customer", "2342342", "--delay", "0", "--error-profile", "server-error")
            output = cli(["verify"], "--mock", "mock-2", "--customer", "2342342", "--delay", "0", "--error-profile", "server-error")
            self.assertIn("2 passed, 0 failed", output)
            self.assertIn("HTTP 500", output)
            cli([], "--mock", "mock-3", "--customer", "3243423434", "--delay", "1000")
            output = cli(["verify"], "--mock", "mock-3", "--customer", "3243423434", "--delay", "1000")
            self.assertIn("1 passed, 0 failed", output)
            cli([], "--mock", "mock-4", "--customer", "2342342", "--error-profile", "timeout")
            output = cli(["verify"], "--mock", "mock-4", "--customer", "2342342", "--error-profile", "timeout")
            self.assertIn("2 passed, 0 failed", output)

            expected = next(m for m in admin("mock-1")["mappings"] if
                            m["metadata"]["wb"]["customer"] == "2342342" and "body" in m["response"])
            shadow = {"id": str(uuid.uuid4()), "priority": 1, "request": expected["request"],
                      "response": {"status": 200, "body": "wrong", "headers": {"Content-Type": "text/plain"}}}
            admin("mock-1", method="POST", body=shadow)
            before = snapshot()
            output = cli(["verify"], "--mock", "mock-1", "--customer", "2342342", "--delay", "0", status=1)
            self.assertIn("1 passed, 1 failed", output)
            self.assertIn("body bytes differ", output)
            self.assertEqual(snapshot(), before)
            print("verified: five mocks and public routes, empty/JSON responses, actual delay, HTTP 500, "
                  "delayed timeout-profile responses, incorrect installed delay rejected, shadow-stub response "
                  "mismatch detected; verification never changed mappings")


if __name__ == "__main__":
    unittest.main(verbosity=2)
