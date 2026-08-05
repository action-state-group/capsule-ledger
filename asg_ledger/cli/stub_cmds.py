# SPDX-License-Identifier: Apache-2.0
"""`asg diff`/`blame`/`bisect`: explicitly out of scope for this task (batch 2,
per the eng-tasks doc) -- stub subcommands with --help text only, so the
verb names are reserved and discoverable without pretending to implement them.
"""
from __future__ import annotations

import argparse
import sys

__all__ = ["add_parsers"]

_STUB_HELP = {
    "diff": "compare the ledger's state between two checkpoints/refs",
    "blame": "trace which decision/record last touched a given field or fold group key",
    "bisect": "binary-search the ledger for the record that introduced a regression",
}


def _run(name: str, _args: argparse.Namespace) -> int:
    print(
        f"asg {name}: not yet implemented -- {_STUB_HELP[name]}. "
        "Out of scope for this task (batch 2, per the eng-tasks doc).",
        file=sys.stderr,
    )
    return 1


def add_parsers(sub: argparse._SubParsersAction) -> None:
    for name, summary in _STUB_HELP.items():
        p = sub.add_parser(
            name,
            help=f"{summary} (not yet implemented -- batch 2)",
            description=(
                f"asg {name}: not yet implemented -- {summary}. "
                "Out of scope for this task (batch 2, per the eng-tasks doc)."
            ),
        )
        p.add_argument("rest", nargs="*", help=argparse.SUPPRESS)
        p.set_defaults(func=lambda args, _name=name: _run(_name, args))
