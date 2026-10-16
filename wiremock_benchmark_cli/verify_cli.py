"""Responsibility: parse verify arguments and report verification outcomes.

Must not: generate independent expectations or mutate WireMock state.
Contract: docs/WB.md, verify installed endpoints.
"""

import math
import sys

from wiremock_benchmark_cli.help import command_parser
from wiremock_benchmark_cli.report import (reported_command, start_report, record, record_source,
                             record_event, record_error)


@reported_command("verify")
def verify_main(argv):
    parser = command_parser("wb verify", "Check installed mappings and probe their public endpoints.",
                            "Examples:\n  wb verify -f wb.phase1.yaml --all-customers\n"
                            "  wb verify --customer 2342342 --mock mock-1 --delay 1000 "
                            "--early-tolerance-ms 10 --max-overhead-ms 100\n"
                            "Sends real configured-method probes sequentially; does not change mappings.\n"
                            "Exit codes: 0 all passed; 1 verification failed; 2 invalid configuration/arguments.")
    parser.add_argument("-f", "--config", default="wb.yaml", help="YAML file (default: ./wb.yaml)")
    selected = parser.add_mutually_exclusive_group(required=True)
    selected.add_argument("--customer", metavar="CODE")
    selected.add_argument("--group", metavar="NAME")
    selected.add_argument("--all-customers", action="store_true")
    targets = parser.add_mutually_exclusive_group()
    targets.add_argument("--mock", metavar="NAME")
    targets.add_argument("--all-mocks", action="store_true", help="Verify all configured mocks (default)")
    parser.add_argument("--delay", type=int, metavar="MS", help="Override file-configured expected delays (optional; match apply overrides)")
    parser.add_argument("--error-profile", metavar="NAME", help="Override file error selection; none selects normal responses (match apply overrides)")
    parser.add_argument("--admin-timeout", type=float, default=15, metavar="SECONDS", help="Admin request timeout (default: 15 seconds)")
    parser.add_argument("--early-tolerance-ms", type=float, default=50, help="Allowed early response tolerance (default: 50ms)")
    parser.add_argument("--max-overhead-ms", type=float, default=1000, help="Allowed overhead above configured delay (default: 1000ms)")
    args = parser.parse_args(argv)
    for name in ("admin_timeout", "early_tolerance_ms", "max_overhead_ms"):
        value = getattr(args, name)
        if not math.isfinite(value) or value < 0 or (name == "admin_timeout" and value == 0):
            parser.error(f"--{name.replace('_', '-')} must be finite and {'positive' if name == 'admin_timeout' else 'nonnegative'}")

    start_report(args)
    from wiremock_benchmark_cli.config import ConfigError, load_config
    from wiremock_benchmark_cli.plan import make_plans
    from wiremock_benchmark_cli.verify import verify_plans

    try:
        plan = make_plans(load_config(args.config, source_observer=record_source), mock=args.mock, all_mocks=args.mock is None,
                          customer=args.customer, group=args.group, all_customers=args.all_customers,
                          delay=args.delay, profile=args.error_profile)
    except ConfigError as exc:
        record_error(exc)
        print(f"wb: {exc}", file=sys.stderr)
        return 2
    record("resolved", plan)
    for target in plan["targets"]:
        for warning in target["warnings"]:
            print(f"WARNING [{target['mock']}]: {warning}", file=sys.stderr)
    count = sum(len(t["mappings"]) for t in plan["targets"])
    seconds = sum(m["response"]["fixedDelayMilliseconds"] for t in plan["targets"] for m in t["mappings"]) / 1000
    print(f"Verifying {count} endpoint(s) sequentially; configured delays total {seconds:g}s. "
          "Sending real configured-method probes; mappings will not be changed.", flush=True)
    results = verify_plans(plan, args.admin_timeout, args.early_tolerance_ms, args.max_overhead_ms,
                           progress=lambda message: print(message, flush=True), observe=record_event)
    passed = sum(result["passed"] for result in results)
    record("summary", {"passed": passed, "failed": len(results) - passed})
    print(f"Verification: {passed} passed, {len(results) - passed} failed.")
    return 0 if passed == len(results) and results else 1
