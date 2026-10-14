"""Responsibility: apply and verify an already validated mapping plan over HTTP.

Must not: resolve configuration, reset mappings, follow redirects or retry writes.
Contract: docs/WB.md, explicit partial failure and stable-ID updates.
"""

import json
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from tools.wb_http_errors import transport_failure


class AdminError(RuntimeError):
    """The admin operation did not meet its verified postcondition."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class WireMockAdmin:
    def __init__(self, base, timeout):
        self.base = base
        self.timeout = timeout
        self.opener = build_opener(NoRedirect())

    def request(self, method, path, body=None, missing_ok=False):
        request = Request(self.base + path, method=method,
                          data=json.dumps(body, allow_nan=False).encode() if body is not None else None,
                          headers={"Accept": "application/json", "Content-Type": "application/json"})
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                payload = response.read()
                if not 200 <= response.status < 300:
                    raise AdminError(f"{method} {path}: unexpected HTTP {response.status}")
                return json.loads(payload) if payload else None
        except HTTPError as exc:
            exc.close()
            if missing_ok and exc.code == 404:
                return None
            raise AdminError(f"{method} {path}: HTTP {exc.code}") from exc
        except (URLError, OSError, ValueError, HTTPException) as exc:
            raise AdminError(f"{method} {path}: {transport_failure(exc)}") from exc


def contains(actual, expected):
    """Allow WireMock's additional defaults, but require every requested value."""
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and contains(actual[key], value) for key, value in expected.items())
    return actual == expected


def mapping_matches(actual, expected):
    """Verify exact body representation and headers, including cleared old fields."""
    if not contains(actual, {key: value for key, value in expected.items() if key != "response"}):
        return False
    response = actual.get("response")
    if not isinstance(response, dict):
        return False
    wanted = expected["response"]
    body_keys = {"body", "jsonBody", "base64Body", "bodyFileName"}
    actual_body = {key: value for key, value in response.items() if key in body_keys}
    wanted_body = {key: value for key, value in wanted.items() if key in body_keys}
    return (actual_body == wanted_body
            and response.get("headers", {}) == wanted["headers"]
            and contains(response, {key: value for key, value in wanted.items()
                                    if key not in body_keys | {"headers"}}))


def apply_plans(plan, timeout, progress=print):
    prepared = []
    verified = 0
    completed = []
    total = sum(len(target["mappings"]) for target in plan["targets"])
    stage = "preflight"
    name = ""
    try:
        # Check every active target before making any change on any target.
        for target in plan["targets"]:
            name = target["mock"]
            if not target["mappings"]:
                progress(f"[{name}] No matching assigned customers; no HTTP requests sent.")
                continue
            admin = WireMockAdmin(target["wiremock_api"], timeout)
            operations = []
            for mapping in target["mappings"]:
                path = "/__admin/mappings/" + mapping["id"]
                current = admin.request("GET", path, missing_ok=True)
                if current is not None:
                    if (not isinstance(current, dict)
                            or current.get("metadata") != mapping["metadata"]):
                        raise AdminError(f"Refusing to overwrite mapping {mapping['id']}: ownership mismatch")
                operations.append((mapping, path, current is not None))
            prepared.append((name, admin, operations))
        for name, admin, operations in prepared:
            for mapping, path, exists in operations:
                stage = "write"
                admin.request("PUT" if exists else "POST", path if exists else "/__admin/mappings", mapping)
                stage = "readback"
                actual = admin.request("GET", path)
                if not mapping_matches(actual, mapping):
                    raise AdminError(f"Readback mismatch for mapping {mapping['id']}")
                verified += 1
                response = mapping["response"]
                progress(f"[{name}] Verified {verified}/{total}: {mapping['request']['urlPath']} "
                         f"status={response['status']} delay={response['fixedDelayMilliseconds']}ms")
            completed.append(name)
            progress(f"[{name}] Applied and verified {len(operations)} mapping(s).")
    except AdminError as exc:
        effects = ("No writes attempted on any target." if stage == "preflight" else
                   "Writes are not atomic and the failing write may have applied.")
        raise AdminError(f"[{name}] {stage} failed: {exc}. Verified {verified}/{total}; "
                         f"completed targets: {', '.join(completed) or '(none)'}. {effects} "
                         "Correct the problem and rerun the same command.") from exc
    return verified
