# SPDX-License-Identifier: Apache-2.0
"""`capsule` CLI entry point: git-style verbs over the ledger query API
(log/show/verify/bundle/blame), the checkpoint surface (checkpoint
emit/status/verify), and signing-key rotation (key rotate/status).

`log`/`show`/`verify`/`bundle` are registered only in the "full" packaging
arm -- see `capsule_ledger/packaging.py` for the two-arm switch. `blame` is
a structural lens over the query API, not an evidence artifact, so it stays
registered in both arms.

The fold/constraints/agents/diff/bisect verbs dissolved to capsule-engine
at W3.2 (#127, fold compute/guard taxonomy/re-evaluation all moved with
their packages) and were deleted from here rather than left registered and
silently broken -- capsule-engine's own CLI is the surface of record for
them now.

This module is a thin dispatcher; each verb's logic lives in its own
`cli/*_cmd.py` (or `*_cmds.py` for a verb group) module.
"""
from __future__ import annotations

import argparse
import sys

from .. import packaging
from . import (
    blame_cmd,
    bundle_cmd,
    checkpoint_cmd,
    key_cmds,
    log_cmd,
    payload_cmd,
    show_cmd,
    verify_cmd,
)

__all__ = ["main"]


def _build_parser(arm: str | None = None) -> argparse.ArgumentParser:
    arm = arm or packaging.current_arm()
    parser = argparse.ArgumentParser(prog="capsule", description="capsule-ledger control plane")
    parser.add_argument("--version", action="store_true", help="print the version and exit")
    sub = parser.add_subparsers(dest="command")

    checkpoint_cmd.add_parser(sub)
    key_cmds.add_parser(sub)
    blame_cmd.add_parser(sub)
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

    if args.command == "key":
        if getattr(args, "key_command", None) is None:
            args.key_parser.print_help()
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
