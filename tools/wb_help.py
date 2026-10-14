"""Responsibility: provide consistent parser help behavior across wb commands.

Must not: load configuration, resolve mappings or perform HTTP operations.
Contract: docs/WB.md, help aliases and command-specific usage.
"""

import argparse


def command_parser(prog, description, epilog):
    parser = argparse.ArgumentParser(
        prog=prog, description=description, epilog=epilog, add_help=False,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-h", "--h", "--help", action="help",
                        help="Show this help and exit")
    return parser
