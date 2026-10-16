"""Responsibility: provide consistent parser help behavior across wb commands.

Must not: load configuration, resolve mappings or perform HTTP operations.
Contract: docs/WB.md, help aliases and command-specific usage.
"""

import argparse

from wiremock_benchmark_cli import __version__


def command_parser(prog, description, epilog):
    parser = argparse.ArgumentParser(
        prog=prog, description=description, epilog=epilog, add_help=False,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-h", "--h", "--help", action="help",
                        help="Show this help and exit")
    parser.add_argument("--version", action="version",
                        version=f"wiremock-benchmark-cli {__version__}",
                        help="Show the application version and exit")
    parser.add_argument("--output", metavar="FILE", help="Write a versioned JSON report (terminal output is retained)")
    parser.add_argument("--overwrite-output", action="store_true", help="Explicitly replace an existing --output file")
    return parser
