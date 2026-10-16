"""Responsibility: resolve the error-profile selection and its configuration source.

Must not: construct responses, resolve delays, perform HTTP or modify configuration.
Contract: docs/WB.md, schema 1 error-profile precedence and explicit none.
"""

from wiremock_benchmark_cli.config import NO_ERROR_PROFILE, error_profile_reference


def resolve_error_profile(config, target, code, override=None):
    assignment = target["customers"][code]
    if override is not None:
        name, source = override, "cli"
    elif "error_profile" in assignment:
        name, source = assignment["error_profile"], "mock-customer"
    elif "error_profile" in config["customers"][code]:
        name, source = config["customers"][code]["error_profile"], "customer"
    else:
        name, source = NO_ERROR_PROFILE, "default"
    error_profile_reference(name, config["error_profiles"], f"customer {code} resolved selection")
    return {"error_profile": name, "error_profile_source": source}
