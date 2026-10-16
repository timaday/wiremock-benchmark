"""Responsibility: discover owned cleanup candidates and verify explicit deletions.

Must not: reset servers, retry mutations, infer ownership from names or resolve YAML.
Contract: docs/WB.md, clean preview, preflight, revalidation and partial outcomes.
"""

import json

from wiremock_benchmark_cli.api import AdminError, WireMockAdmin
from wiremock_benchmark_cli.identity import owned_customer


def complete_mappings(value):
    if not isinstance(value, dict) or not isinstance(value.get("mappings"), list):
        raise AdminError("Invalid mapping list response")
    mappings = value["mappings"]
    meta = value.get("meta")
    if not isinstance(meta, dict) or type(meta.get("total")) is not int or meta["total"] != len(mappings):
        raise AdminError("Mapping list is incomplete or has invalid total; no cleanup can be planned")
    ids = [mapping.get("id") for mapping in mappings if isinstance(mapping, dict)]
    if len(ids) != len(mappings) or any(not isinstance(value, str) for value in ids) or len(set(ids)) != len(ids):
        raise AdminError("Mapping list contains invalid or duplicate IDs")
    return mappings


def clean_targets(targets, customer, stale_only, execute, timeout=15, progress=print, observe=lambda event: None):
    candidates = []
    deleted = absent = attempted = 0
    name = ""
    active_id = None
    try:
        # Read and validate every selected target before the first DELETE.
        for target in targets:
            name = target["mock"]
            admin = WireMockAdmin(target["api"], timeout)
            mappings = complete_mappings(admin.request("GET", "/__admin/mappings"))
            unrecognized = 0
            for mapping in mappings:
                code = owned_customer(mapping)
                if code is None:
                    unrecognized += 1
                    continue
                if customer is not None and code != customer:
                    continue
                stale = mapping["id"] not in target["desired_ids"]
                if stale_only and not stale:
                    continue
                candidates.append((name, admin, mapping))
                request = mapping.get("request", {})
                # JSON escaping prevents mapping data from injecting terminal lines.
                route = {key: request[key] for key in ("method", "urlPath", "url", "urlPattern", "urlPathPattern")
                         if isinstance(request, dict) and key in request}
                observe({"operation": "candidate", "mock": name, "mapping_id": mapping["id"],
                         "customer": code, "request": route, "stale": stale})
                progress(f"CANDIDATE [{name}] id={mapping['id']} customer={json.dumps(code)} "
                         f"request={json.dumps(route, sort_keys=True)}; "
                         f"{'stale ID absent from configuration' if stale else 'selected owned mapping'}")
            progress(f"[{name}] Preserved {unrecognized} mapping(s) with unrecognized ownership.")
        progress(f"{'Execute' if execute else 'Preview'}: {len(candidates)} mapping(s) selected.")
        if not execute:
            progress("No mappings changed. Add --execute to recalculate and delete candidates.")
            return {"candidates": len(candidates), "deleted": 0, "absent": 0}
        for name, admin, mapping in candidates:
            active_id = mapping["id"]
            path = "/__admin/mappings/" + mapping["id"]
            current = admin.request("GET", path, missing_ok=True)
            if current is None:
                absent += 1
                observe({"operation": "delete", "status": "already-absent", "mock": name, "mapping_id": active_id})
                progress(f"ABSENT [{name}] {mapping['id']}")
                continue
            if current != mapping or owned_customer(current) != owned_customer(mapping):
                raise AdminError(f"Mapping {mapping['id']} changed since discovery; refusing deletion")
            attempted += 1
            observe({"operation": "delete", "status": "attempted", "mock": name, "mapping_id": active_id})
            admin.request("DELETE", path)
            if admin.request("GET", path, missing_ok=True) is not None:
                raise AdminError(f"Mapping {mapping['id']} still exists after DELETE")
            deleted += 1
            observe({"operation": "delete", "status": "verified", "mock": name, "mapping_id": active_id})
            progress(f"DELETED [{name}] {mapping['id']} (absence verified)")
    except AdminError as exc:
        observe({"operation": "clean", "status": "failed", "mock": name, "mapping_id": active_id,
                 "detail": str(exc), "deleted": deleted, "absent": absent, "attempted": attempted})
        effects = ("No DELETE requests attempted." if attempted == 0 else
                   "Deletion is not atomic; an unverified DELETE may have applied. Inspect before rerunning.")
        raise AdminError(f"[{name}] cleanup failed: {exc}. Verified deletions={deleted}; "
                         f"already absent={absent}; DELETE attempts={attempted}. {effects}") from exc
    progress(f"Cleanup: {deleted} deletion(s) verified; {absent} already absent.")
    return {"candidates": len(candidates), "deleted": deleted, "absent": absent}
