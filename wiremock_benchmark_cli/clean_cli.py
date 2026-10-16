"""Responsibility: parse clean scope and resolve target expectations for cleanup.

Must not: decide ownership, duplicate endpoint resolution or issue HTTP requests.
Contract: docs/WB.md, explicit cleanup selectors and preview by default.
"""

import math
import sys

from wiremock_benchmark_cli.help import command_parser
from wiremock_benchmark_cli.report import (reported_command, start_report, record, record_source,
                             record_event, record_error)


@reported_command("clean")
def clean_main(argv):
    parser = command_parser("wb clean", "Preview wb-owned mapping removal; deletion requires --execute.",
                            "Examples:\n  wb clean -f wb.phase1.yaml --mock mock-5 --customer 2342342 --stale-only --dry-run\n"
                            "  wb clean --mock mock-5 --customer 2342342 --stale-only --execute\n"
                            "  wb clean --all-mocks --all-customers\n"
                            "Without --stale-only, currently configured owned mappings are also selected.\n"
                            "Exit codes: 0 success; 1 cleanup/admin failure; 2 invalid configuration/arguments.")
    parser.add_argument("-f", "--config", default="wb.yaml", help="YAML file (default: ./wb.yaml)")
    targets = parser.add_mutually_exclusive_group(required=True)
    targets.add_argument("--mock", metavar="NAME", help="One configured target")
    targets.add_argument("--all-mocks", action="store_true", help="All configured targets")
    customers = parser.add_mutually_exclusive_group(required=True)
    customers.add_argument("--customer", metavar="CODE", help="Owned customer code, including one removed from YAML")
    customers.add_argument("--all-customers", action="store_true", help="All owned customer codes, including removed customers")
    parser.add_argument("--stale-only", action="store_true", help="Only owned IDs absent from this target's current configuration")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Explicit preview: read live mappings without deleting them (default)")
    mode.add_argument("--execute", action="store_true", help="Delete candidates and verify absence")
    parser.add_argument("--admin-timeout", type=float, default=15, metavar="SECONDS", help="Admin timeout (default: 15 seconds)")
    args = parser.parse_args(argv)
    if not math.isfinite(args.admin_timeout) or args.admin_timeout <= 0:
        parser.error("--admin-timeout must be a positive finite number")

    start_report(args)
    from wiremock_benchmark_cli.api import AdminError
    from wiremock_benchmark_cli.clean import clean_targets
    from wiremock_benchmark_cli.config import ConfigError, load_config, segment
    from wiremock_benchmark_cli.plan import configured_endpoints

    try:
        config = load_config(args.config, source_observer=record_source)
        if args.mock is not None and args.mock not in config["wiremocks"]:
            raise ConfigError(f"Unknown mock: {args.mock}")
        if args.customer is not None:
            segment(args.customer, "customer code")
        selected = config["wiremocks"] if args.all_mocks else {args.mock: config["wiremocks"][args.mock]}
        targets = [{"mock": name, "api": target["api"], "desired_ids": {
            endpoint["mapping_id"] for endpoint in configured_endpoints(config, target, target["customers"])}}
            for name, target in selected.items()]
    except ConfigError as exc:
        record_error(exc)
        print(f"wb: {exc}", file=sys.stderr)
        return 2
    record("resolved", {"targets": [{**target, "desired_ids": sorted(target["desired_ids"])}
                                    for target in targets]})
    try:
        summary = clean_targets(targets, args.customer, args.stale_only, args.execute, args.admin_timeout,
                      progress=lambda message: print(message, flush=True), observe=record_event)
    except AdminError as exc:
        record_error(exc)
        print(f"wb: {exc}", file=sys.stderr)
        return 1
    record("summary", {**summary, "mode": "execute" if args.execute else "preview"})
    return 0
