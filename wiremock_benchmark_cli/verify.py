"""Responsibility: check installed mappings and probe their public HTTP endpoints.

Must not: change mappings, retry requests or derive expectations from live state.
Contract: docs/WB.md, verify installed endpoints.
"""

from http.client import HTTPException
import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from wiremock_benchmark_cli.api import AdminError, NoRedirect, WireMockAdmin, mapping_matches
from wiremock_benchmark_cli.http_errors import transport_failure
from wiremock_benchmark_cli.requests import probe_payload
from wiremock_benchmark_cli.verify_expectations import expected_bytes, expected_criteria, timing_bounds


def json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def response_problem(response, status, headers, body, elapsed_ms, early_ms, overhead_ms, *, head=False):
    if status != response["status"]:
        return f"HTTP status {status}; expected {response['status']}"
    for name, value in response["headers"].items():
        if headers.get_all(name) != [value]:
            return f"response header {name} does not match"
    if head:
        if body:
            return "HEAD response must have no body"
    elif "body" in response:
        if body != expected_bytes(response):
            return f"body bytes differ (received {len(body)}, expected {len(expected_bytes(response))})"
        if (not body and not any(name.lower() == "content-type" for name in response["headers"])
                and headers.get("Content-Type") is not None):
            return "unexpected Content-Type on empty response"
    else:
        try:
            actual = json.loads(body, object_pairs_hook=json_object)
            if json.dumps(actual, sort_keys=True, allow_nan=False) != json.dumps(response["jsonBody"], sort_keys=True, allow_nan=False):
                return "JSON response content/types differ"
        except (ValueError, UnicodeError, RecursionError):
            return "response body is not valid unambiguous JSON"
    lower, upper = timing_bounds(response, early_ms, overhead_ms)
    if not lower <= elapsed_ms <= upper:
        return (f"response time {elapsed_ms:.1f}ms outside "
                f"{lower:.1f}–{upper:.1f}ms")
    return None


def probe(url, mapping, early_ms, overhead_ms, *, request_settings):
    response = mapping["response"]
    timeout = (response["fixedDelayMilliseconds"] + overhead_ms) / 1000 + 5
    opener = build_opener(NoRedirect())
    data, headers = probe_payload(request_settings)
    request = Request(url, method=mapping["request"]["method"], data=data, headers=headers)
    started = time.monotonic()
    try:
        limit = max(1048576, len(expected_bytes(response)) * 4)
        try:
            connection = opener.open(request, timeout=timeout)
        except HTTPError as error:
            connection = error
        with connection:
            body = connection.read(limit + 1)
            elapsed_ms = (time.monotonic() - started) * 1000
            if len(body) > limit:
                return False, f"response body exceeds {limit} byte verification limit"
            problem = response_problem(response, connection.status, connection.headers, body,
                                       elapsed_ms, early_ms, overhead_ms, head=mapping["request"]["method"] == "HEAD")
            return (False, problem) if problem else (True, f"HTTP {connection.status}; {len(body)} bytes; {elapsed_ms:.1f}ms")
    except (URLError, OSError, HTTPException, ValueError, OverflowError) as exc:
        return False, f"probe transport failure: {transport_failure(exc)}"


def verify_plans(plan, admin_timeout=15, early_ms=50, overhead_ms=1000, progress=print, observe=lambda event: None):
    results = []
    for target in plan["targets"]:
        if not target["mappings"]:
            progress(f"[{target['mock']}] No matching assigned customers; no HTTP requests sent.")
            continue
        admin = WireMockAdmin(target["wiremock_api"], admin_timeout)
        for mapping, url, resolved in zip(target["mappings"], target["request_urls"], target["resolved_profiles"], strict=True):
            progress(f"CHECK [{target['mock']}] {mapping['request']['method']} {url}")
            progress(f"  Request profile: {resolved['request_profile']} ({resolved['request_profile_source']})")
            progress("  Probe body: " + json.dumps(resolved["probe_body"], allow_nan=False))
            progress(f"  Delay source: {resolved['delay_source']}")
            progress(f"  Error profile: {resolved['error_profile']} ({resolved['error_profile_source']})")
            for line in expected_criteria(mapping, early_ms, overhead_ms):
                progress(line)
            try:
                actual = admin.request("GET", "/__admin/mappings/" + mapping["id"])
                if not mapping_matches(actual, mapping):
                    passed, detail = False, "installed mapping differs from expected configuration; probe not sent"
                else:
                    passed, detail = probe(url, mapping, early_ms, overhead_ms, request_settings=resolved)
            except AdminError as exc:
                passed, detail = False, f"admin check failed: {exc}; probe not sent"
            result = {"mock": target["mock"], "url": url, "passed": passed, "detail": detail}
            results.append(result)
            observe({"operation": "verify", "mapping_id": mapping["id"], **result})
            progress(f"{'PASS' if passed else 'FAIL'} [{target['mock']}] {url}: {detail}")
    return results
