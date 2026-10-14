"""Responsibility: own mapping IDs, ownership metadata and endpoint-scope values.

Must not: read configuration, choose endpoints or perform HTTP operations.
Contract: docs/WB.md, stable identities and recognized wb ownership.
"""

import json
import uuid


CUSTOMER_SCOPE = "customer"
PRODUCT_CLASS_SCOPE = "product-class"


def mapping_id(code, product, uri_extension=""):
    if product is None and uri_extension:
        identity = "urn:wiremock-benchmark:wb:customer-extension:v1:" + json.dumps([code, uri_extension], ensure_ascii=True)
        return str(uuid.uuid5(uuid.NAMESPACE_URL, identity))
    identity = ("urn:wiremock-benchmark:wb:customer:v1:" + json.dumps(code, ensure_ascii=True)
                if product is None else
                "urn:wiremock-benchmark:wb:v1:" + json.dumps([code, product], ensure_ascii=True))
    return str(uuid.uuid5(uuid.NAMESPACE_URL, identity))


def mapping_metadata(code, product, uri_extension=""):
    owner = {"version": 1, "customer": code} | (
        {"productClass": product} if product is not None else {"endpointScope": CUSTOMER_SCOPE})
    if product is None and uri_extension:
        owner["uriExtension"] = uri_extension
    return {"wb": owner}


def owned_customer(mapping):
    """Recognize only complete known ownership metadata and its canonical ID."""
    if not isinstance(mapping, dict):
        return None
    metadata = mapping.get("metadata")
    if not isinstance(metadata, dict) or set(metadata) != {"wb"}:
        return None
    owner = metadata["wb"]
    if not isinstance(owner, dict) or type(owner.get("version")) is not int or owner["version"] != 1:
        return None
    code = owner.get("customer")
    if not isinstance(code, str) or not code:
        return None
    extension = ""
    if set(owner) == {"version", "customer", "productClass"}:
        product = owner["productClass"]
        if not isinstance(product, str) or not product:
            return None
    elif set(owner) == {"version", "customer", "endpointScope"} and owner["endpointScope"] == CUSTOMER_SCOPE:
        product = None
    elif set(owner) == {"version", "customer", "endpointScope", "uriExtension"} and owner["endpointScope"] == CUSTOMER_SCOPE:
        product = None
        extension = owner["uriExtension"]
        if not isinstance(extension, str) or not extension:
            return None
    else:
        return None
    return code if mapping.get("id") == mapping_id(code, product, extension) else None
