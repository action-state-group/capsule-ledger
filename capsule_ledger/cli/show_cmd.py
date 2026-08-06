# SPDX-License-Identifier: Apache-2.0
"""`capsule show <capsule_id>`: git-show-style detail view of one ledger record."""
from __future__ import annotations

import argparse
import json
import sys

from .format import build_echo, summarize_action
from .ledger_io import open_ledger, require_ledger_path

__all__ = ["add_parser", "run"]


def add_parser(sub: argparse._SubParsersAction) -> argparse.ArgumentParser:
    p = sub.add_parser("show", help="show one ledger record in full (git-show style)")
    p.add_argument("capsule_id", help="a capsule_id or an unambiguous prefix")
    p.add_argument("--ledger", help="ledger store directory or a JSONL fixture file (default: $CAPSULE_LEDGER)")
    p.add_argument("--json", action="store_true", help="print the raw capsule JSON instead of the formatted view")
    p.set_defaults(func=run)
    return p


def run(args: argparse.Namespace) -> int:
    # This command only exists at all in the "full" packaging arm (see
    # ``cli/main.py``), so unprompted use of it is exactly M5's
    # "evidence feature touched" -- record once per install.
    from ..telemetry.record import record_evidence_touch

    record_evidence_touch("full")

    ledger_path = require_ledger_path("show", args)
    if ledger_path is None:
        return 2

    with open_ledger(ledger_path) as store:
        record = store.fetch(args.capsule_id)
        if record is None:
            print(f"no such capsule {args.capsule_id!r} in ledger {ledger_path}", file=sys.stderr)
            return 1

        if args.json:
            print(json.dumps(record.capsule, indent=2, sort_keys=True))
            return 0

        capsule = record.capsule
        disposition = capsule.get("disposition") or {}
        assurance = capsule.get("assurance") or {}
        chain = capsule.get("chain") or {}
        constraints = capsule.get("constraints") or []

        print(f"capsule {record.capsule_id}")
        print(f"Agent:      {capsule.get('developer', '')}")
        print(f"Operator:   {capsule.get('operator', '')}")
        print(f"Action:     {summarize_action(capsule)} ({capsule.get('action_type', '')})")
        print(f"Date:       {capsule.get('timestamp', '')}")
        print(f"Verdict:    {disposition.get('verdict_class') or '(none)'}")
        print(f"Assurance:  {assurance.get('attestation_mode', '')} · {assurance.get('ledger_mode', '')}")
        if chain:
            print(f"Chain:      {chain.get('parent_capsule_id')} ({chain.get('relation')})")
        else:
            print("Chain:      (none)")
        if constraints:
            print("Constraints:")
            for c in constraints:
                print(f"  - {c.get('id')}: {c.get('result')}")
        else:
            print("Constraints: (none)")
        print()
        print(build_echo("show", positional=record.capsule_id))
    return 0
