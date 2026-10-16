"""Opt-in CLI smoke against a dedicated upstream WireMock through its public ingress.

Set WB_INTEGRATION_API to an isolated test endpoint; creates uniquely named
mappings and retains them. No reset or deletion is performed.
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
class WireMockCliSmoke(unittest.TestCase):
    def test_real_customer_updates_profiles_and_nginx_paths(self):
        base = os.environ["WB_INTEGRATION_API"].rstrip("/")
        config = yaml.safe_load((ROOT / "wb.yaml").read_text())
        suffix = uuid.uuid4().hex[:10]
        first, second = "first-" + suffix, "second-" + suffix
        config["customers"] = {
            first: dict(name="Test Customer", response_profile="accepted", error_profile="none", delay_ms=1000, allowed_delays_ms=[0, 1000, 6000], endpoint_scope="product-class",
                        ProductClasses={"Productclass": None}),
            second: dict(name="Customer Two", response_profile="accepted", error_profile="none", delay_ms=1000, allowed_delays_ms=[0, 1000, 6000], endpoint_scope="product-class",
                         ProductClasses={"C++": None, "Prödüct.v1": None}),
        }
        config["wiremocks"] = {"smoke": dict(api=base, prefix_handling="strip", customers={first: {}, second: {}})}
        config["customer_groups"] = {"one-customer": [first]}
        config["error_profiles"]["timeout"]["delay_ms"] = 600
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wb.yaml"
            path.write_text(yaml.safe_dump(config))

            def cli(*arguments):
                result = subprocess.run([str(ROOT / "wb"), "--config", str(path), "--mock", "smoke", *arguments],
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout

            def request(url, method="GET", data=None, timeout=10):
                with urlopen(Request(url, method=method, data=data,
                                     headers={"Content-Type": "application/json"}), timeout=timeout) as response:
                    return response.status, json.loads(response.read())

            existing = request(base + "/__admin/mappings")[1]["mappings"]
            sentinel = {"id": str(uuid.uuid4()), "request": {"method": "POST", "urlPath": "/keep-" + suffix},
                        "response": {"status": 200, "jsonBody": {"untouched": True}}}
            request(base + "/__admin/mappings", "POST", json.dumps(sentinel).encode())
            cli("--all-customers", "--delay", "1000")
            plan = json.loads(cli("--all-customers", "--delay", "1000", "--dry-run"))["targets"][0]
            for url in plan["request_urls"]:
                started = time.monotonic()
                status, body = request(url + "?ignored=1", "POST", b'{"any":"body"}')
                elapsed = time.monotonic() - started
                self.assertEqual(status, 200)
                self.assertEqual(body, config["response_profiles"]["accepted"]["jsonBody"])
                self.assertGreaterEqual(elapsed, 0.95)
                print(f"success: {elapsed:.3f}s {url}")
            cli("--all-customers", "--delay", "1000")
            self.assertEqual(len(request(base + "/__admin/mappings")[1]["mappings"]), len(existing) + 4)

            cli("--group", "one-customer", "--delay", "6000")
            started = time.monotonic()
            self.assertEqual(request(plan["request_urls"][0], "POST", b"")[0], 200)
            elapsed = time.monotonic() - started
            self.assertGreaterEqual(elapsed, 5.95)
            print(f"updated six-second response: {elapsed:.3f}s")
            for mapping in plan["mappings"][1:]:
                actual = request(base + "/__admin/mappings/" + mapping["id"])[1]
                self.assertEqual(actual["response"]["fixedDelayMilliseconds"], 1000)

            cli("--customer", first, "--delay", "0", "--error-profile", "server-error")
            with self.assertRaises(HTTPError) as error:
                request(plan["request_urls"][0], "POST", b"")
            self.assertEqual(error.exception.code, 500)
            self.assertEqual(json.loads(error.exception.read()), config["error_profiles"]["server-error"]["response"]["jsonBody"])
            error.exception.close()

            cli("--customer", first, "--error-profile", "timeout")
            with self.assertRaises(TimeoutError):
                request(plan["request_urls"][0], "POST", b"", timeout=0.1)
            # Allow the intentionally delayed request to finish before changing its mapping.
            time.sleep(0.6)
            cli("--customer", first, "--delay", "0")
            self.assertEqual(request(plan["request_urls"][0], "POST", b"")[1], config["response_profiles"]["accepted"]["jsonBody"])
            for url in (plan["request_urls"][0] + "/wrong",):
                with self.assertRaises(HTTPError) as error:
                    request(url, "POST", b"")
                self.assertEqual(error.exception.code, 404)
                error.exception.close()
            with self.assertRaises(HTTPError) as error:
                request(plan["request_urls"][0], "GET")
            self.assertEqual(error.exception.code, 404)
            error.exception.close()
            self.assertEqual(request(base + sentinel["request"]["urlPath"], "POST", b"")[1], {"untouched": True})
            final = request(base + "/__admin/mappings")[1]["mappings"]
            self.assertEqual(len(final), len(existing) + 4)
            for mapping in existing:
                self.assertIn(mapping, final)
            print("verified: idempotent updates, selected-customer isolation, HTTP 500, timeout, restore, unrelated mapping retained")


if __name__ == "__main__":
    unittest.main(verbosity=2)
