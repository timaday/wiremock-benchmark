"""Responsibility: derive and display probe expectations from a resolved mapping.

Must not: read live state, resolve profiles or decide verification outcomes.
Contract: docs/WB.md, per-endpoint expected criteria and timing bounds.
"""

import json


def expected_bytes(response):
    if "body" in response:
        return response["body"].encode("utf-8")
    return json.dumps(response["jsonBody"], ensure_ascii=False, allow_nan=False).encode("utf-8")


def timing_bounds(response, early_ms, overhead_ms):
    delay = response["fixedDelayMilliseconds"]
    return max(0, delay - early_ms), delay + overhead_ms


def expected_criteria(mapping, early_ms, overhead_ms):
    response = mapping["response"]
    lower, upper = timing_bounds(response, early_ms, overhead_ms)
    lines = [
        f"  Expected mapping: id={mapping['id']}; method={mapping['request']['method']}; "
        f"urlPath={mapping['request']['urlPath']}; owned configuration must match",
        f"  Expected status: HTTP {response['status']}",
        "  Expected headers: " + json.dumps(response["headers"], sort_keys=True)
        + " (configured values must match; extra headers allowed)",
    ]
    if mapping["request"]["method"] == "HEAD":
        lines.append("  Expected body: empty for HEAD; configured response body is checked through the admin API")
    elif "body" in response:
        lines.append(f"  Expected body: {len(expected_bytes(response))} UTF-8 bytes; exact match "
                     + json.dumps(response["body"]))
        if not response["body"] and not any(name.lower() == "content-type" for name in response["headers"]):
            lines.append("  Expected Content-Type: absent")
    else:
        lines.append("  Expected body: JSON content/types must match (object order/whitespace ignored): "
                     + json.dumps(response["jsonBody"], sort_keys=True, allow_nan=False))
    lines.append(f"  Expected delay: {response['fixedDelayMilliseconds']}ms; "
                 f"response time {lower:.1f}–{upper:.1f}ms")
    return lines
