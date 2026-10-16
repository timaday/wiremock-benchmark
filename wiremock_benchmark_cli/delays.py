"""Responsibility: resolve delay using the canonical error-profile selection.

Must not: perform HTTP, read YAML, derive timing from server state or alter config.
Contract: docs/WB.md, schema 1 delay precedence and timeout-profile exception;
return error selection as a read-only projection from wb_error_profiles.
"""

from wiremock_benchmark_cli.config import (ConfigError, MAX_DELAY_MS, NO_ERROR_PROFILE,
                             error_profile_reference, integer, validate_delay)
from wiremock_benchmark_cli.error_profiles import resolve_error_profile


def validate_delay_options(config, delay, profile):
    if delay is not None:
        integer(delay, 0, MAX_DELAY_MS, "--delay")
    if profile is not None:
        error_profile_reference(profile, config["error_profiles"], "--error-profile")


def resolve_delay(config, target, code, delay=None, profile=None):
    validate_delay_options(config, delay, profile)
    customer = config["customers"][code]
    assignment = target["customers"][code]
    selection = resolve_error_profile(config, target, code, profile)
    name = selection["error_profile"]
    if name != NO_ERROR_PROFILE and config["error_profiles"][name]["type"] == "timeout":
        if delay is not None:
            raise ConfigError(f"Customer {code}: a timeout profile supplies its own delay; omit --delay "
                              "or select --error-profile none")
        return {**selection, "delay_ms": config["error_profiles"][name]["delay_ms"], "delay_source": "timeout-profile"}
    if delay is not None:
        value, source = delay, "cli"
    elif "delay_ms" in assignment:
        value, source = assignment["delay_ms"], "mock-customer"
    else:
        value, source = customer["delay_ms"], "customer"
    validate_delay(value, customer, f"customer {code} resolved delay")
    return {**selection, "delay_ms": value, "delay_source": source}
