"""`asg` CLI entry point: git-style verbs over the ledger query API
(log/show/verify/bundle), the fold catalog (fold list/new/test/lint), the
guard-check/action-class catalog (constraints list), a per-agent summary
(agents --status), and the guard API's dry-run report (guard dry-run).
`diff`/`blame`/`bisect` are stubbed only -- batch 2.

This module is a thin dispatcher; each verb's logic lives in its own
`cli/*_cmd.py` (or `*_cmds.py` for a verb group) module.
"""
from __future__ import annotations

import argparse
import sys

from . import (
    agents_cmd,
    bundle_cmd,
    constraints_cmd,
    fold_cmds,
    guard_cmds,
    log_cmd,
    show_cmd,
    stub_cmds,
    verify_cmd,
)

__all__ = ["main"]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="asg", description="asg-ledger control plane")
    parser.add_argument("--version", action="store_true", help="print the version and exit")
    sub = parser.add_subparsers(dest="command")

    fold_cmds.add_parser(sub)
    log_cmd.add_parser(sub)
    show_cmd.add_parser(sub)
    verify_cmd.add_parser(sub)
    bundle_cmd.add_parser(sub)
    constraints_cmd.add_parser(sub)
    agents_cmd.add_parser(sub)
    guard_cmds.add_parser(sub)
    stub_cmds.add_parsers(sub)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.version:
        from asg_ledger import __version__

        print(__version__)
        return 0

    if args.command == "fold":
        if getattr(args, "fold_command", None) is None:
            args.fold_parser.print_help()
            return 0
        return args.func(args)

    if args.command == "guard":
        if getattr(args, "guard_command", None) is None:
            args.guard_parser.print_help()
            return 0
        return args.func(args)

    if args.command == "constraints":
        if getattr(args, "constraints_command", None) is None:
            args.constraints_parser.print_help()
            return 0
        return args.func(args)

    if args.command is None:
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
