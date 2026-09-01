# SPDX-License-Identifier: Apache-2.0
"""`capsule` CLI entry point: git-style verbs over the ledger query API
(log/show/verify/bundle/diff/blame/bisect), the fold catalog (fold
list/new/test/lint), the guard-check/action-class catalog (constraints
list), a per-agent summary (agents --status), telemetry disclosure/funnel
reporting (telemetry status/funnel), and signing-key rotation (key
rotate/status).

`log`/`show`/`verify`/`bundle` are registered only in the "full" packaging
arm -- see `capsule_ledger/packaging.py` for the two-arm switch. `diff`/`blame`/
`bisect` are structural lenses over the query API, not evidence
artifacts, so they stay registered in both arms.

This module is a thin dispatcher; each verb's logic lives in its own
`cli/*_cmd.py` (or `*_cmds.py` for a verb group) module.
"""
from __future__ import annotations

import argparse
import sys

from .. import packaging
from . import (
    agents_cmd,
    bisect_cmd,
    blame_cmd,
    bundle_cmd,
    checkpoint_cmd,
    constraints_cmd,
    diff_cmd,
    fold_cmds,
    key_cmds,
    log_cmd,
    payload_cmd,
    show_cmd,
    telemetry_cmd,
    verify_cmd,
)

__all__ = ["main"]


def _build_parser(arm: str | None = None) -> argparse.ArgumentParser:
    arm = arm or packaging.current_arm()
    parser = argparse.ArgumentParser(prog="capsule", description="capsule-ledger control plane")
    parser.add_argument("--version", action="store_true", help="print the version and exit")
    sub = parser.add_subparsers(dest="command")

    fold_cmds.add_parser(sub)
    checkpoint_cmd.add_parser(sub)
    constraints_cmd.add_parser(sub)
    agents_cmd.add_parser(sub)
    key_cmds.add_parser(sub)
    diff_cmd.add_parser(sub)
    blame_cmd.add_parser(sub)
    bisect_cmd.add_parser(sub)
    telemetry_cmd.add_parser(sub)
    # The record-query/evidence verbs -- git-log-style listing, single-record
    # show, capsule verify, and the shareable bundle -- are the "evidence":
    # registered only in the "full" arm. See ``packaging.py``'s module
    # docstring for why an env var, not a fork, drives this.
    if packaging.evidence_visible(arm):
        log_cmd.add_parser(sub)
        show_cmd.add_parser(sub)
        verify_cmd.add_parser(sub)
        bundle_cmd.add_parser(sub)
        payload_cmd.add_parser(sub)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.version:
        from capsule_ledger import __version__

        print(__version__)
        return 0

    from ..telemetry.record import record_install_seen

    record_install_seen(packaging.current_arm())

    if args.command == "fold":
        if getattr(args, "fold_command", None) is None:
            args.fold_parser.print_help()
            return 0
        return args.func(args)

    if args.command == "key":
        if getattr(args, "key_command", None) is None:
            args.key_parser.print_help()
            return 0
        return args.func(args)

    if args.command == "constraints":
        if getattr(args, "constraints_command", None) is None:
            args.constraints_parser.print_help()
            return 0
        return args.func(args)

    if args.command == "telemetry":
        if getattr(args, "telemetry_command", None) is None:
            args.telemetry_parser.print_help()
            return 0
        return args.func(args)

    if args.command == "payload":
        if getattr(args, "payload_command", None) is None:
            args.payload_parser.print_help()
            return 0
        return args.func(args)

    if args.command == "checkpoint":
        if getattr(args, "checkpoint_command", None) is None:
            args.cp_parser.print_help()
            return 0
        return args.func(args)

    if args.command is None:
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
