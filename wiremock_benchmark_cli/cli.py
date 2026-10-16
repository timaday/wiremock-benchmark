"""Responsibility: parse wb arguments and present configuration/application outcomes.

Must not: own mapping resolution or WireMock HTTP behavior.
Contract: docs/WB.md.
"""

import json
import math
import sys

from wiremock_benchmark_cli.api import AdminError, apply_plans
from wiremock_benchmark_cli.help import command_parser
from wiremock_benchmark_cli.report import (reported_command, start_report, record, record_source,
                             record_event, record_error)


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        if arguments and arguments[0] == "apply":
            return apply_main(arguments[1:], explicit=True)
        if arguments and arguments[0] == "list":
            from wiremock_benchmark_cli.list import list_main
            return list_main(arguments[1:])
        if arguments and arguments[0] == "verify":
            from wiremock_benchmark_cli.verify_cli import verify_main
            return verify_main(arguments[1:])
        if arguments and arguments[0] == "clean":
            from wiremock_benchmark_cli.clean_cli import clean_main
            return clean_main(arguments[1:])
        return apply_main(arguments)
    except ModuleNotFoundError as exc:
        if exc.name != "yaml":
            raise
        print("wb: PyYAML is missing; reinstall wiremock-benchmark-cli with its dependencies", file=sys.stderr)
        return 2


@reported_command("apply")
def apply_main(argv, explicit=False):
    overview = ("Commands:\n"
                "  apply   Apply customer mappings (default when no command is given).\n"
                "  list    List YAML-configured endpoints without network requests.\n"
                "  verify  Check installed mappings and send real HTTP probes.\n"
                "  clean   Preview or explicitly delete wb-owned mappings.\n"
                "Use wb COMMAND --help for command-specific options.\n\n")
    examples = ("Examples:\n"
                "  wb apply -f wb.phase1.yaml --all-mocks --all-customers --dry-run\n"
                "  wb apply --mock mock-1 --customer 2342342 --delay 6000\n"
                "  wb apply --mock mock-1 --customer 2342342 --error-profile timeout\n"
                "Apply writes mappings; --dry-run prints the plan without HTTP requests.")
    parser = command_parser("wb apply" if explicit else "wb",
                            "Configure WireMock customer mappings from YAML.",
                            ("" if explicit else overview) + examples)
    parser.add_argument("-f", "--config", default="wb.yaml", help="YAML file (default: ./wb.yaml)")
    targets = parser.add_mutually_exclusive_group(required=True)
    targets.add_argument("--mock", metavar="NAME", help="One named YAML target")
    targets.add_argument("--all-mocks", action="store_true", help="All named YAML targets")
    parser.add_argument("--wiremock-api", help="Override the API URL for one explicit --mock")
    selected = parser.add_mutually_exclusive_group(required=True)
    selected.add_argument("--customer", metavar="CODE")
    selected.add_argument("--group", metavar="NAME", help="Named YAML customer group")
    selected.add_argument("--all-customers", action="store_true")
    parser.add_argument("--delay", type=int, metavar="MS", help="Override file-configured delays for selected endpoints (optional)")
    parser.add_argument("--error-profile", metavar="NAME", help="Override file error selection: named HTTP-error/timeout profile, or none for normal responses")
    parser.add_argument("--dry-run", action="store_true", help="Print the plan without contacting WireMock")
    parser.add_argument("--admin-timeout", type=float, default=15, metavar="SECONDS")
    args = parser.parse_args(argv)
    if not math.isfinite(args.admin_timeout) or args.admin_timeout <= 0:
        parser.error("--admin-timeout must be a positive finite number")
    start_report(args)
    from wiremock_benchmark_cli.config import ConfigError, load_config
    from wiremock_benchmark_cli.plan import make_plans
    try:
        plan = make_plans(load_config(args.config, source_observer=record_source), mock=args.mock, all_mocks=args.all_mocks,
                          customer=args.customer, group=args.group, all_customers=args.all_customers,
                          delay=args.delay, profile=args.error_profile, override=args.wiremock_api)
    except ConfigError as exc:
        record_error(exc)
        print(f"wb: {exc}", file=sys.stderr)
        return 2
    record("resolved", plan)
    for target in plan["targets"]:
        for warning in target["warnings"]:
            print(f"WARNING [{target['mock']}]: {warning}", file=sys.stderr)
    if args.dry_run:
        record("summary", {"mode": "dry-run", "live_state_checked": False})
        print(json.dumps(plan, indent=2, ensure_ascii=False))
        return 0
    for target in plan["targets"]:
        print(f"[{target['mock']}] {len(target['mappings'])} mapping(s) to {target['wiremock_api']}; "
              f"customers={','.join(target['customers']) or '(none)'}; "
              f"prefix_handling={target['prefix_handling']}")
        for resolved in target["resolved_profiles"]:
            print(f"  customer={resolved['customer']} mapping={resolved['mapping_id']} "
                  f"delay={resolved['delay_ms']}ms source={resolved['delay_source']}; "
                  f"error_profile={resolved['error_profile']} ({resolved['error_profile_source']})")
            print(f"    method={resolved['method']}; request_profile={resolved['request_profile']} "
                  f"({resolved['request_profile_source']}); probe_body={json.dumps(resolved['probe_body'])}")
    try:
        count = apply_plans(plan, args.admin_timeout, observe=record_event)
    except AdminError as exc:
        record_error(exc)
        print(f"wb: {exc}", file=sys.stderr)
        return 1
    record("summary", {"verified": count})
    print(f"Applied and verified {count} mapping(s).")
    return 0
