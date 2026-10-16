"""Responsibility: load and validate the customer, target and group configuration.

Must not: perform HTTP requests or mutate WireMock state.
Contract: docs/WB.md, configuration schema version 1.
"""

import json
import re
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import yaml

from wiremock_benchmark_cli.identity import CUSTOMER_SCOPE, PRODUCT_CLASS_SCOPE

CONFIG_SCHEMA_VERSION = 1
MAX_DELAY_MS = 2147483647
NO_ERROR_PROFILE = "none"


class ConfigError(ValueError):
    """The requested configuration cannot produce an unambiguous mapping plan."""


class UniqueKeyLoader(yaml.SafeLoader):
    """Reject duplicate mapping keys instead of silently retaining the last one."""

    def construct_mapping(self, node, deep=False):
        self.flatten_mapping(node)
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                if key in result:
                    raise ConfigError(f"Duplicate YAML key at line {key_node.start_mark.line + 1}")
                result[key] = self.construct_object(value_node, deep=deep)
            except TypeError as exc:
                raise ConfigError("YAML mapping keys must be scalars") from exc
        return result


def fields(value, required, optional, where):
    if not isinstance(value, dict):
        raise ConfigError(f"{where} must be a mapping")
    if not required <= value.keys() or value.keys() - required - optional:
        raise ConfigError(f"{where}: required fields {sorted(required)}; optional {sorted(optional)}")


def integer(value, minimum, maximum, where):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ConfigError(f"{where} must be an integer between {minimum} and {maximum}")


def endpoint_scope(value, where):
    if value not in (CUSTOMER_SCOPE, PRODUCT_CLASS_SCOPE):
        raise ConfigError(f"{where}: endpoint_scope must explicitly be customer or product-class")


def validate_delay(value, customer, where):
    integer(value, 0, MAX_DELAY_MS, where)
    if "allowed_delays_ms" in customer and value not in customer["allowed_delays_ms"]:
        raise ConfigError(f"{where}: delay {value}ms is not allowed by allowed_delays_ms")


def segment(value, where):
    if not isinstance(value, str) or not value or value != value.strip():
        raise ConfigError(f"{where} must be a nonempty string without surrounding whitespace")
    if value in (".", "..") or re.search(r"[/\\%?;#\x00-\x1f\x7f]", value):
        raise ConfigError(f"{where} contains a reserved path character or dot segment")
    # Keep legal path punctuation literal: Nginx decodes %2B to + upstream.
    # Semicolons are excluded above because servlet containers treat them as parameters.
    return quote(value, safe="!$&'()*+,:=@")


def relative_path(value, where, allow_empty=False):
    """Validate and encode relative path segments without silently normalizing them."""
    if not isinstance(value, str):
        raise ConfigError(f"{where} must be a string")
    if value == "" and allow_empty:
        return ""
    return "/".join(segment(part, f"{where} segment") for part in value.split("/"))


def api_base(value):
    if not isinstance(value, str) or not value or re.search(r"[\s\x00-\x1f\x7f]", value):
        raise ConfigError("WireMock API URL must be an HTTP(S) base URL without whitespace")
    try:
        parts = urlsplit(value)
        port = parts.port
        if (parts.scheme not in ("http", "https") or not parts.hostname
                or parts.username is not None or parts.password is not None
                or parts.query or parts.fragment or "?" in value or "#" in value
                or port == 0):
            raise ValueError()
        path = parts.path.rstrip("/")
        if ("/__admin" in path or any(p in (".", "..") for p in path.split("/"))
                or "//" in path or "%" in path or "\\" in value):
            raise ValueError()
    except ValueError as exc:
        raise ConfigError("WireMock API URL must be an HTTP(S) base URL, without credentials, "
                          "query, fragment, encoded prefix or /__admin") from exc
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def json_value(value):
    """Reject YAML-only types, non-string object keys, cycles and nonfinite numbers."""
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ConfigError("jsonBody keys must be strings")
        for item in value.values():
            json_value(item)
    elif isinstance(value, list):
        for item in value:
            json_value(item)
    elif value is not None and type(value) not in (str, int, float, bool):
        raise ConfigError("jsonBody must contain only JSON-compatible values")


def validate_response(value, error=False):
    optional = {"body", "jsonBody"} | ({"request_profile"} if not error else set())
    fields(value, {"status", "headers"}, optional, "profile response")
    integer(value["status"], 400 if error else 200, 599 if error else 299, "response.status")
    if ("body" in value) + ("jsonBody" in value) != 1:
        raise ConfigError("Each response must declare exactly one of body or jsonBody")
    if "body" in value:
        if not isinstance(value["body"], str):
            raise ConfigError('response.body must be a string; use "" for an empty response')
    else:
        if not isinstance(value["jsonBody"], dict):
            raise ConfigError("response.jsonBody must be a JSON object")
        try:
            json_value(value["jsonBody"])
            json.dumps(value["jsonBody"], allow_nan=False)
        except (ValueError, TypeError, RecursionError) as exc:
            raise ConfigError("response.jsonBody must be a finite, non-recursive JSON object") from exc
    if value["status"] in (204, 205) and value.get("body") != "":
        raise ConfigError('HTTP 204/205 profiles require body: ""')
    headers = value["headers"]
    if not isinstance(headers, dict):
        raise ConfigError("response.headers must be a mapping of strings")
    for key, val in headers.items():
        if (not isinstance(key, str) or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", key)
                or not isinstance(val, str) or re.search(r"[\x00-\x1f\x7f]", val)):
            raise ConfigError("response.headers contains an invalid header name or value")


def profile_reference(name, profiles, where):
    segment(name, f"{where} response_profile")
    if name not in profiles:
        raise ConfigError(f"{where}: unknown response profile {name}")


def customer_references(value, customers, where):
    if not isinstance(value, list) or not value:
        raise ConfigError(f"{where} must be a nonempty list of customer codes")
    codes = []
    for code in value:
        if type(code) not in (str, int):
            raise ConfigError(f"{where}: customer codes must be strings or integers")
        code = str(code)
        if code not in customers:
            raise ConfigError(f"{where}: unknown customer {code}")
        if code in codes:
            raise ConfigError(f"{where}: duplicate customer {code}")
        codes.append(code)
    return codes


def error_profile_reference(name, profiles, where):
    if not isinstance(name, str) or (name != NO_ERROR_PROFILE and name not in profiles):
        raise ConfigError(f"{where}: error_profile must be none or a known profile name")


def validate_targets_and_groups(data):
    targets = data["wiremocks"]
    if not isinstance(targets, dict) or not targets:
        raise ConfigError("wiremocks must be a nonempty mapping")
    endpoints = set()
    for name, target in targets.items():
        segment(name, "mock name")
        fields(target, {"api", "prefix_handling", "customers"}, set(), f"mock {name}")
        target["api"] = api_base(target["api"])
        if target["prefix_handling"] not in ("strip", "preserve"):
            raise ConfigError(f"mock {name}: prefix_handling must explicitly be strip or preserve")
        parts = urlsplit(target["api"])
        if target["prefix_handling"] == "strip" and not parts.path:
            raise ConfigError(f"mock {name}: prefix_handling=strip requires a URL path prefix; "
                              "use preserve for a direct root URL")
        identity = (parts.scheme, parts.hostname.lower(), parts.port or
                    (443 if parts.scheme == "https" else 80), parts.path)
        if identity in endpoints:
            raise ConfigError(f"mock {name}: duplicate API endpoint")
        endpoints.add(identity)
        assignments = target["customers"]
        if not isinstance(assignments, dict) or not assignments:
            raise ConfigError(f"mock {name}: customers must be a nonempty mapping of code to explicit override settings or {{}}")
        codes = customer_references(list(assignments), data["customers"], f"mock {name}")
        normalized = {}
        for code, settings in zip(codes, assignments.values(), strict=True):
            fields(settings, set(), {"delay_ms", "error_profile"}, f"mock {name} customer {code}")
            if "error_profile" in settings:
                error_profile_reference(settings["error_profile"], data["error_profiles"], f"mock {name} customer {code}")
            if "delay_ms" in settings:
                validate_delay(settings["delay_ms"], data["customers"][code], f"mock {name} customer {code} delay_ms")
            normalized[code] = settings
        target["customers"] = normalized
    if not isinstance(data["customer_groups"], dict):
        raise ConfigError("customer_groups must be a mapping")
    for name, members in data["customer_groups"].items():
        segment(name, "group name")
        data["customer_groups"][name] = customer_references(members, data["customers"], f"group {name}")


def load_config(path, source_observer=None):
    from wiremock_benchmark_cli.requests import REQUEST_FIELDS, request_profile_reference, validate_request_profiles
    try:
        content = Path(path).read_bytes()
        if source_observer is not None:
            source_observer(path, content)
        data = yaml.load(content.decode("utf-8"), Loader=UniqueKeyLoader)
    except (OSError, UnicodeError) as exc:
        raise ConfigError(f"Cannot read configuration file: {type(exc).__name__}") from exc
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        location = f" at line {mark.line + 1}" if mark else ""
        raise ConfigError(f"Invalid YAML{location}") from exc
    if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] != CONFIG_SCHEMA_VERSION:
        raise ConfigError("schema_version must be the integer 1; migrate unversioned files using docs/WB.md")
    if isinstance(data, dict) and ("wiremock_api" in data or "prefix_handling" in data):
        raise ConfigError("Single-target YAML has been replaced: use wiremocks with api, "
                          "prefix_handling and customers per target, plus customer_groups (see docs/WB.md)")
    if isinstance(data, dict) and "response" in data:
        raise ConfigError("Global response has been replaced: use response_profiles and an explicit "
                          "response_profile for every customer (see docs/WB.md)")
    fields(data, {"schema_version", "wiremocks", "customer_groups", "response_profiles", "customers", "error_profiles"}, {"request_profiles"}, "configuration")
    data.setdefault("request_profiles", {})
    validate_request_profiles(data["request_profiles"])
    responses = data["response_profiles"]
    if not isinstance(responses, dict) or not responses:
        raise ConfigError("response_profiles must be a nonempty mapping")
    for name, response in responses.items():
        segment(name, "response profile name")
        validate_response(response)
        if "request_profile" in response:
            request_profile_reference(response["request_profile"], data["request_profiles"], f"response profile {name}")
    if not isinstance(data["customers"], dict) or not data["customers"]:
        raise ConfigError("customers must be a nonempty mapping")
    customers = {}
    for code, customer in data["customers"].items():
        if type(code) not in (str, int):
            raise ConfigError("Customer codes must be strings or integers; quote numeric codes")
        code = str(code)
        segment(code, "customer code")
        if code in customers:
            raise ConfigError("Duplicate customer code after string conversion")
        fields(customer, {"name", "endpoint_scope", "response_profile", "delay_ms"}, {"error_profile", "ProductClasses", "uri_extension", "customer_path_override", "allowed_delays_ms"} | REQUEST_FIELDS, f"customer {code}")
        if "request_profile" in customer:
            request_profile_reference(customer["request_profile"], data["request_profiles"], f"customer {code}")
        segment(customer["name"], f"customer {code} name")
        if "uri_extension" in customer:
            relative_path(customer["uri_extension"], "uri_extension", allow_empty=True)
        if "customer_path_override" in customer:
            relative_path(customer["customer_path_override"], "customer_path_override")
        endpoint_scope(customer["endpoint_scope"], f"customer {code}")
        profile_reference(customer["response_profile"], responses, f"customer {code}")
        if "allowed_delays_ms" in customer:
            delays = customer["allowed_delays_ms"]
            if not isinstance(delays, list) or not delays:
                raise ConfigError(f"customer {code} allowed_delays_ms must be a nonempty list")
            for delay in delays:
                integer(delay, 0, MAX_DELAY_MS, f"customer {code} allowed_delays_ms")
            if len(set(delays)) != len(delays):
                raise ConfigError(f"customer {code} has duplicate allowed delays")
        validate_delay(customer["delay_ms"], customer, f"customer {code} delay_ms")
        products = customer.get("ProductClasses", {})
        if not isinstance(products, dict):
            raise ConfigError(f"customer {code} ProductClasses must be a mapping")
        if not products and customer["endpoint_scope"] == PRODUCT_CLASS_SCOPE:
            raise ConfigError(f"customer {code}: product-class scope requires a nonempty ProductClasses mapping")
        customer["ProductClasses"] = products
        for product, settings in products.items():
            segment(product, "product class")
            if settings is not None:
                fields(settings, set(), {"response_profile", "endpoint_scope", "uri_extension"} | REQUEST_FIELDS, f"product {product}")
                if not settings:
                    raise ConfigError(f"product {product}: declare response_profile, endpoint_scope, uri_extension or request_profile; use null to inherit all")
                if "request_profile" in settings:
                    request_profile_reference(settings["request_profile"], data["request_profiles"], f"customer {code} product {product}")
                if "uri_extension" in settings:
                    relative_path(settings["uri_extension"], "uri_extension", allow_empty=True)
                if "response_profile" in settings:
                    profile_reference(settings["response_profile"], responses, f"customer {code} product {product}")
                if "endpoint_scope" in settings:
                    endpoint_scope(settings["endpoint_scope"], f"customer {code} product {product}")
        customers[code] = customer
    data["customers"] = customers
    profiles = data["error_profiles"]
    if not isinstance(profiles, dict):
        raise ConfigError("error_profiles must be a mapping")
    for name, profile in profiles.items():
        segment(name, "error profile name")
        if name == NO_ERROR_PROFILE:
            raise ConfigError("error_profiles: none is reserved for the normal response")
        if not isinstance(profile, dict) or profile.get("type") not in ("http-error", "timeout"):
            raise ConfigError("Error profile type must be http-error or timeout")
        if profile["type"] == "http-error":
            fields(profile, {"type", "response"}, set(), f"profile {name}")
            validate_response(profile["response"], error=True)
        else:
            fields(profile, {"type", "delay_ms"}, set(), f"profile {name}")
            integer(profile["delay_ms"], 1, MAX_DELAY_MS, f"profile {name} delay_ms")
    for code, customer in customers.items():
        if "error_profile" in customer:
            error_profile_reference(customer["error_profile"], profiles, f"customer {code}")
    validate_targets_and_groups(data)
    return data
