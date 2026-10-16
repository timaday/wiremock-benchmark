"""Verify response profile transitions through a dedicated public WireMock ingress.

Set WB_INTEGRATION_API to an isolated Nginx /mock-N route. Unique mappings are
retained; existing mappings and other customers must remain unchanged.
"""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import uuid

import yaml


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get("WB_INTEGRATION_API"), "Set WB_INTEGRATION_API to a dedicated test ingress")
class ResponseProfilesSmoke(unittest.TestCase):
    def test_json_empty_text_transitions_and_profile_inheritance(self):
        base = os.environ["WB_INTEGRATION_API"].rstrip("/")
        config = yaml.safe_load((ROOT / "wb.yaml").read_text())
        first, other = [prefix + uuid.uuid4().hex[:10] for prefix in ("profiles-", "other-")]
        config["customers"] = {
            first: dict(name="Profile Customer", response_profile="accepted", error_profile="none", delay_ms=1000, allowed_delays_ms=[0, 1000], endpoint_scope="product-class",
                        ProductClasses={"Inherited": None, "Override": {"response_profile": "accepted"}}),
            other: dict(name="Unchanged Customer", response_profile="accepted", error_profile="none", delay_ms=1000, allowed_delays_ms=[0, 1000], endpoint_scope="product-class",
                        ProductClasses={"Product": None}),
        }
        config["wiremocks"] = {"smoke": dict(api=base, prefix_handling="strip", customers={first: {}, other: {}})}
        config["customer_groups"] = {"selected": [first]}
        config["response_profiles"]["accepted"]["headers"]["X-Profile"] = "accepted"
        config["response_profiles"]["text-ok"] = {"status": 200, "headers": {"Content-Type": "text/plain"}, "body": "Ready"}
        config["error_profiles"]["timeout"]["delay_ms"] = 600

        def request(path, method="GET", timeout=5):
            try:
                response = urlopen(Request(base + path, method=method, data=b"{}" if method == "POST" else None), timeout=timeout)
            except HTTPError as error:
                response = error
            with response:
                return response.status, response.headers, response.read()

        def mappings():
            status, _, body = request("/__admin/mappings")
            self.assertEqual(status, 200)
            return {m["id"]: m for m in json.loads(body)["mappings"]}

        original = mappings()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wb.yaml"

            def cli(*arguments, exit_code=0):
                path.write_text(yaml.safe_dump(config, sort_keys=False))
                result = subprocess.run([str(ROOT / "wb"), "--config", str(path), "--mock", "smoke", *arguments],
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, exit_code, result.stdout + result.stderr)
                return result

            cli("--all-customers", "--delay", "0")
            plan = json.loads(cli("--customer", first, "--delay", "0", "--dry-run").stdout)["targets"][0]
            chosen = {m["metadata"]["wb"]["productClass"]: m for m in plan["mappings"]}
            stable_ids = set(mappings())
            untouched = {key: value for key, value in mappings().items()
                         if key not in {m["id"] for m in chosen.values()}}

            def check_json(product):
                status, headers, body = request(chosen[product]["request"]["urlPath"], "POST")
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(body), config["response_profiles"]["accepted"]["jsonBody"])
                self.assertEqual(headers.get("X-Profile"), "accepted")
                self.assertIn("application/json", headers.get("Content-Type"))

            def check_empty(product):
                status, headers, body = request(chosen[product]["request"]["urlPath"], "POST")
                self.assertEqual(status, 200)
                self.assertEqual(body, b"")
                self.assertIsNone(headers.get("Content-Type"))
                self.assertIsNone(headers.get("X-Profile"))
                stored = mappings()[chosen[product]["id"]]["response"]
                self.assertNotIn("jsonBody", stored)
                self.assertEqual(stored.get("headers", {}), {})

            check_json("Inherited")
            check_json("Override")
            config["customers"][first]["response_profile"] = "empty-ok"
            cli("--group", "selected", "--delay", "1000")
            started = time.monotonic()
            check_empty("Inherited")
            elapsed = time.monotonic() - started
            self.assertGreaterEqual(elapsed, 0.95)
            check_json("Override")
            profiles = json.loads(cli("--customer", first, "--delay", "0", "--dry-run").stdout)["targets"][0]["resolved_profiles"]
            self.assertEqual([(p["response_profile"], p["source"]) for p in profiles],
                             [("empty-ok", "customer"), ("accepted", "product")])

            cli("--customer", first, "--error-profile", "timeout")
            with self.assertRaises(TimeoutError):
                request(chosen["Inherited"]["request"]["urlPath"], "POST", timeout=0.1)
            time.sleep(0.6)
            cli("--customer", first, "--delay", "0", "--error-profile", "server-error")
            for product in chosen:
                status, headers, body = request(chosen[product]["request"]["urlPath"], "POST")
                self.assertEqual(status, 500)
                self.assertIsNone(headers.get("X-Profile"))
                self.assertEqual(json.loads(body), config["error_profiles"]["server-error"]["response"]["jsonBody"])
            cli("--customer", first, "--delay", "0")
            check_empty("Inherited")
            check_json("Override")

            config["customers"][first]["ProductClasses"]["Override"]["response_profile"] = "empty-ok"
            cli("--customer", first, "--delay", "0")
            check_empty("Override")
            config["customers"][first]["ProductClasses"]["Override"] = None
            for profile in ("text-ok", "accepted"):
                config["customers"][first]["response_profile"] = profile
                cli("--customer", first, "--delay", "0")
                for product in chosen:
                    if profile == "accepted":
                        check_json(product)
                    else:
                        status, headers, body = request(chosen[product]["request"]["urlPath"], "POST")
                        self.assertEqual((status, body), (200, b"Ready"))
                        self.assertIn("text/plain", headers.get("Content-Type"))
                        self.assertIsNone(headers.get("X-Profile"))
            final = mappings()
            self.assertEqual(set(final), stable_ids)
            for key, value in untouched.items():
                self.assertEqual(final[key], value)
            for key, value in original.items():
                self.assertEqual(final[key], value)
            print(f"verified: empty HTTP 200 with zero bytes ({elapsed:.3f}s at 1000ms delay), "
                  "customer inheritance, explicit overrides, JSON/empty/text transitions, cleared headers, "
                  "error/timeout profiles, stable IDs and unaffected customers")


if __name__ == "__main__":
    unittest.main(verbosity=2)
