"""Responsibility: validate and resolve named request profiles and encode probes.

Must not: perform HTTP, choose mapping IDs or construct response expectations.
Contract: docs/WB.md, request method and verification body in schema version 1.
"""

import copy
import json

from wiremock_benchmark_cli.config import ConfigError, fields, json_value, segment


REQUEST_FIELDS = {"request_profile"}
DEFAULT_PROFILE = "default"
DEFAULT_REQUEST = {"method": "POST", "probe_body": {"type": "json", "value": {}}}
METHODS = {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}
BODYLESS_METHODS = {"GET", "HEAD"}


def validate_request_definition(settings, where):
    fields(settings, {"method", "probe_body"}, set(), where)
    method = settings["method"]
    if not isinstance(method, str) or method not in METHODS:
        raise ConfigError(f"{where}: method must be one of {', '.join(sorted(METHODS))}")
    body = settings["probe_body"]
    if not isinstance(body, dict) or body.get("type") not in ("json", "text", "none"):
        raise ConfigError(f"{where}: probe_body must declare type json, text or none")
    kind = body["type"]
    fields(body, {"type"} if kind == "none" else {"type", "value"}, set(), f"{where} probe_body")
    if method in BODYLESS_METHODS and kind != "none":
        raise ConfigError(f"{where}: {method} requires probe_body: {{type: none}}; bodies are not discarded")
    try:
        if kind == "json":
            json_value(body["value"])
            json.dumps(body["value"], ensure_ascii=False, allow_nan=False).encode("utf-8")
        elif kind == "text":
            if not isinstance(body["value"], str):
                raise ConfigError(f"{where}: text probe_body.value must be a string")
            body["value"].encode("utf-8")
    except (ValueError, TypeError, RecursionError, UnicodeError) as exc:
        raise ConfigError(f"{where}: probe_body.value must be valid UTF-8 text or finite JSON for its type") from exc


def validate_request_profiles(profiles):
    if not isinstance(profiles, dict):
        raise ConfigError("request_profiles must be a mapping")
    for name, definition in profiles.items():
        segment(name, "request profile name")
        if name == DEFAULT_PROFILE:
            raise ConfigError("request_profiles: default is reserved and cannot be redefined")
        validate_request_definition(definition, f"request profile {name}")


def request_profile_reference(name, profiles, where):
    if not isinstance(name, str) or (name != DEFAULT_PROFILE and name not in profiles):
        raise ConfigError(f"{where}: request_profile must be default or a known profile name")


def resolve_request(config, customer, product=None, *, response_profile):
    """Select one complete profile without merging definitions or changing inputs."""
    if product is not None and "request_profile" in product:
        name, source = product["request_profile"], "product"
    elif "request_profile" in customer:
        name, source = customer["request_profile"], "customer"
    elif "request_profile" in config["response_profiles"][response_profile]:
        name, source = config["response_profiles"][response_profile]["request_profile"], "response-profile"
    else:
        name, source = DEFAULT_PROFILE, "default"
    request_profile_reference(name, config["request_profiles"], "resolved request")
    definition = DEFAULT_REQUEST if name == DEFAULT_PROFILE else config["request_profiles"][name]
    return {**copy.deepcopy(definition), "request_profile": name, "request_profile_source": source}


def probe_payload(settings):
    """Encode the resolved declaration without interpreting server state."""
    body = settings["probe_body"]
    if body["type"] == "none":
        return None, {"Accept-Encoding": "identity"}
    if body["type"] == "json":
        data = json.dumps(body["value"], ensure_ascii=False, allow_nan=False).encode("utf-8")
        content_type = "application/json"
    else:
        data = body["value"].encode("utf-8")
        content_type = "text/plain; charset=utf-8"
    return data, {"Content-Type": content_type, "Accept-Encoding": "identity"}
