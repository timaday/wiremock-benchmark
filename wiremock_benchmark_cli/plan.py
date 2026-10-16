"""Responsibility: resolve explicit target/customer selections into mapping plans.

Must not: load YAML or perform HTTP operations.
Contract: docs/WB.md schema 1; explicit target assignments and profile inheritance.
"""

import copy
from urllib.parse import urlsplit

from wiremock_benchmark_cli.config import NO_ERROR_PROFILE, PRODUCT_CLASS_SCOPE, ConfigError, api_base, relative_path, segment
from wiremock_benchmark_cli.delays import resolve_delay, validate_delay_options
from wiremock_benchmark_cli.identity import mapping_id, mapping_metadata
from wiremock_benchmark_cli.requests import resolve_request


def configured_endpoints(config, target, codes):
    """Own endpoint paths, stable IDs and profile inheritance for apply and list."""
    base = target["api"]
    prefix = urlsplit(base).path
    mode = target["prefix_handling"]
    if mode == "strip" and not prefix:
        raise ConfigError("prefix_handling=strip requires a URL path prefix; "
                          "use preserve for a direct root URL")
    endpoints = []
    paths = {}
    identities = {}
    for code in codes:
        customer = config["customers"][code]
        timing = resolve_delay(config, target, code)
        customer_path = ("/" + relative_path(customer["customer_path_override"], "customer_path_override")
                         if "customer_path_override" in customer else
                         f"/{segment(customer['name'], 'name')}/{segment(code, 'code')}")
        # An empty product collection explicitly represents one customer endpoint.
        entries = customer["ProductClasses"].items() if customer["ProductClasses"] else [(None, None)]
        for product, settings in entries:
            profile_override = settings is not None and "response_profile" in settings
            scope_override = settings is not None and "endpoint_scope" in settings
            extension_override = settings is not None and "uri_extension" in settings
            source = "product" if profile_override else "customer"
            profile = settings["response_profile"] if profile_override else customer["response_profile"]
            request = resolve_request(config, customer, settings, response_profile=profile)
            method = request["method"]
            scope = settings["endpoint_scope"] if scope_override else customer["endpoint_scope"]
            extension = settings["uri_extension"] if extension_override else customer.get("uri_extension", "")
            extension_source = "product" if extension_override else ("customer" if "uri_extension" in customer else "none")
            path = customer_path
            if extension:
                path += "/" + relative_path(extension, "uri_extension", allow_empty=True)
            if scope == PRODUCT_CLASS_SCOPE:
                path += f"/productClasses/{segment(product, 'product')}"
            endpoint_id = mapping_id(code, product if scope == PRODUCT_CLASS_SCOPE else None, extension)
            route = (method, path)
            if endpoint_id in identities and identities[endpoint_id] != route:
                raise ConfigError(f"Conflicting request methods or paths for shared mapping {endpoint_id}; "
                                  "use one method or distinct product-class routes")
            identities[endpoint_id] = route
            if route in paths:
                existing = paths[route]
                if existing["mapping_id"] != endpoint_id:
                    raise ConfigError(f"Conflicting endpoint scopes or customers on {method} {base + path}; choose distinct routes")
                if existing["response_profile"] != profile:
                    raise ConfigError(f"Conflicting response profiles on shared {method} endpoint {base + path}: "
                                      f"{existing['response_profile']} and {profile}; use one profile or product-class scope")
                if existing["request_profile"] != request["request_profile"]:
                    raise ConfigError(f"Conflicting request profiles on shared {method} endpoint {base + path}")
                existing["product_classes"].append(product)
                if existing["request_profile_source"] != request["request_profile_source"]:
                    existing["request_profile_source"] = "mixed"
                if existing["source"] != source:
                    existing["source"] = "mixed"
                if existing["scope_source"] != ("product" if scope_override else "customer"):
                    existing["scope_source"] = "mixed"
                if existing["extension_source"] != extension_source:
                    existing["extension_source"] = "mixed"
                continue
            endpoint = {
                "mapping_id": endpoint_id,
                "customer": code, "product_class": product if scope == PRODUCT_CLASS_SCOPE else None,
                "product_classes": [product] if product is not None else [], "request_url": base + path,
                "mapping_path": prefix + path if mode == "preserve" else path,
                "response_profile": profile, "source": source,
                "endpoint_scope": scope, "scope_source": "product" if scope_override else "customer",
                "uri_extension": extension, "extension_source": extension_source,
                **timing, **request,
            }
            paths[route] = endpoint
            endpoints.append(endpoint)
    return endpoints


def resolved_response(config, profile, delay, error_profile):
    error = config["error_profiles"][error_profile] if error_profile != NO_ERROR_PROFILE else None
    definition = (error["response"] if error and error["type"] == "http-error"
                  else config["response_profiles"][profile])
    response = copy.deepcopy({key: value for key, value in definition.items() if key != "request_profile"})
    response["fixedDelayMilliseconds"] = delay
    return response


def target_plan(name, target, config, codes, delay, error_profile):
    base = target["api"]
    prefix = urlsplit(base).path
    mode = target["prefix_handling"]
    warnings = ([f"prefix_handling=strip explicitly excludes {prefix} from mappings. "
                 "The proxy must remove this prefix before forwarding customer requests."]
                if mode == "strip" else [])
    if not codes:
        warnings.append("No assigned customers match this selection; this mock will not be contacted.")
    mappings, request_urls, resolved_profiles = [], [], []
    for endpoint in configured_endpoints(config, target, codes):
        code, product = endpoint["customer"], endpoint["product_class"]
        timing = resolve_delay(config, target, code, delay, error_profile)
        response = resolved_response(config, endpoint["response_profile"], timing["delay_ms"], timing["error_profile"])
        request_urls.append(endpoint["request_url"])
        resolved_profiles.append({key: endpoint[key] for key in
                                  ("mapping_id", "customer", "product_class", "response_profile", "source",
                                   "endpoint_scope", "scope_source", "product_classes", "uri_extension", "extension_source",
                                   "method", "request_profile", "probe_body", "request_profile_source")}
                                 | timing)
        mappings.append({
            "id": endpoint["mapping_id"],
            "name": f"wb: {code} / {product}" if product is not None else f"wb: {code} / shared customer route",
            "metadata": mapping_metadata(code, product, endpoint["uri_extension"]),
            "request": {"method": endpoint["method"], "urlPath": endpoint["mapping_path"]},
            "response": response,
        })
    return {"mock": name, "wiremock_api": base, "prefix_handling": mode,
            "customers": codes, "warnings": warnings, "request_urls": request_urls,
            "resolved_profiles": resolved_profiles, "mappings": mappings}


def make_plans(config, *, mock=None, all_mocks=False, customer=None, group=None,
               all_customers=False, delay=None, profile=None, override=None):
    if (mock is not None) + bool(all_mocks) != 1:
        raise ConfigError("Select exactly one of --mock or --all-mocks")
    if (customer is not None) + (group is not None) + bool(all_customers) != 1:
        raise ConfigError("Select exactly one of --customer, --group or --all-customers")
    if mock is not None and mock not in config["wiremocks"]:
        raise ConfigError(f"Unknown mock: {mock}")
    if customer is not None and customer not in config["customers"]:
        raise ConfigError(f"Unknown customer: {customer}")
    if group is not None and group not in config["customer_groups"]:
        raise ConfigError(f"Unknown group: {group}")
    if override is not None and all_mocks:
        raise ConfigError("--wiremock-api requires one explicit --mock; cannot override --all-mocks")
    targets = copy.deepcopy(config["wiremocks"] if all_mocks else {mock: config["wiremocks"][mock]})
    if override is not None:
        targets[mock]["api"] = api_base(override)
    assigned = {code for target in targets.values() for code in target["customers"]}
    if all_customers:
        requested = assigned
    elif customer is not None:
        requested = {customer}
    else:
        requested = set(config["customer_groups"][group])
    uncovered = requested - assigned
    if uncovered:
        raise ConfigError("Requested customers are not assigned to any selected mock: " + ", ".join(sorted(uncovered)))
    validate_delay_options(config, delay, profile)
    return {"targets": [target_plan(name, target, config,
                                    [code for code in target["customers"] if code in requested], delay, profile)
                        for name, target in targets.items()]}
