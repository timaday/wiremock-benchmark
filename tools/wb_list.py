"""Responsibility: present YAML-configured endpoints as a read-only CLI listing.

Must not: contact WireMock, infer live state or own endpoint/profile resolution.
Contract: docs/WB.md, list configured endpoints.
"""

import sys
import json

from tools.wb_help import command_parser


def list_main(argv):
    parser = command_parser("wb list", "List configured endpoints from YAML; no network requests.",
                            "Examples:\n  wb list -f wb.phase1.yaml --all-customers\n"
                            "  wb list --customer 2342342 --mock mock-1\n"
                            "Lists configured expectations; does not check installed mappings.")
    parser.add_argument("-f", "--config", default="wb.yaml", help="YAML file (default: ./wb.yaml)")
    selected = parser.add_mutually_exclusive_group(required=True)
    selected.add_argument("--customer", metavar="CODE")
    selected.add_argument("--all-customers", action="store_true")
    targets = parser.add_mutually_exclusive_group()
    targets.add_argument("--mock", metavar="NAME", help="Restrict listing to one named mock")
    targets.add_argument("--all-mocks", action="store_true", help="List all configured mocks (the listing default)")
    args = parser.parse_args(argv)

    from tools.wb_config import ConfigError, load_config
    from tools.wb_plan import configured_endpoints

    try:
        config = load_config(args.config)
        if args.customer is not None and args.customer not in config["customers"]:
            raise ConfigError(f"Unknown customer: {args.customer}")
        if args.mock is not None and args.mock not in config["wiremocks"]:
            raise ConfigError(f"Unknown mock: {args.mock}")
        customers = list(config["customers"]) if args.all_customers else [args.customer]
        mocks = config["wiremocks"] if args.mock is None else {args.mock: config["wiremocks"][args.mock]}
        endpoints = {name: configured_endpoints(config, target,
                     [code for code in customers if code in target["customers"]])
                     for name, target in mocks.items()}
    except ConfigError as exc:
        print(f"wb: {exc}", file=sys.stderr)
        return 2

    print(f"Configured endpoints from {args.config} (YAML only; live state not checked).")
    total = 0
    for code in customers:
        print(f"\nCustomer {code}: {config['customers'][code]['name']}")
        count = 0
        for name, target in mocks.items():
            if code not in target["customers"]:
                continue
            for endpoint in endpoints[name]:
                if endpoint["customer"] != code:
                    continue
                print(f"  [{name}] {endpoint['method']} {endpoint['request_url']}")
                print(f"    product={','.join(endpoint['product_classes']) or '(customer endpoint)'}; profile={endpoint['response_profile']} "
                      f"({endpoint['source']}); prefix_handling={target['prefix_handling']}; "
                      f"mapping_path={endpoint['mapping_path']}")
                print(f"    endpoint_scope={endpoint['endpoint_scope']} ({endpoint['scope_source']})")
                print(f"    uri_extension={json.dumps(endpoint['uri_extension'])} ({endpoint['extension_source']})")
                count += 1
        if count == 0:
            print("  No configured endpoints in the selected mocks.")
        total += count
    print(f"\n{total} configured endpoint(s).")
    return 0
