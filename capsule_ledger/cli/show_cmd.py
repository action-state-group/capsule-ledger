# SPDX-License-Identifier: Apache-2.0
"""`capsule show <capsule_id>`: git-show-style detail view of one ledger record."""
from __future__ import annotations

import argparse
import json
import sys

from ..conversation import find_turn_reference
from .format import (
    build_echo,
    format_action_class,
    format_assurance_grade,
    format_resolved_payload,
    summarize_action,
)
from .ledger_io import local_payload_store, open_ledger, require_ledger_path

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

    payload_store = local_payload_store(ledger_path)

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
        action_class_line = format_action_class(capsule)
        if action_class_line:
            print(f"Action class: {action_class_line}")
        print(f"Date:       {capsule.get('timestamp', '')}")
        print(f"Verdict:    {disposition.get('verdict_class') or '(none)'}")
        print(f"Assurance:  {format_assurance_grade(assurance)}")
        reason_digest = disposition.get("reason_digest")
        if reason_digest:
            print(f"Reason:     digest {reason_digest}")
            if payload_store is not None:
                resolved = payload_store.resolve(reason_digest)
                if resolved is not None:
                    for line in format_resolved_payload("reason", resolved):
                        print(line)
        if chain:
            print(f"Chain:      {chain.get('parent_capsule_id')} ({chain.get('relation')})")
        else:
            print("Chain:      (none)")
        # A conversation turn may name this capsule as one it gave rise to
        # (``build_turn_reference_capsule``) -- e.g. a tool-call capsule some
        # other pipeline recorded, layered on top of the conversation
        # profile. Resolved by scan since the reference is often built and
        # appended after this capsule already exists (the turn is only
        # knowable once a full trajectory is available), so this capsule
        # itself never carries the link.
        turn_reference = find_turn_reference(store, record.capsule_id)
        if turn_reference is not None:
            turn_capsule_id = turn_reference.capsule["asg_payload"]["detail"]["turn_capsule_id"]
            print(f"Turn:       {turn_capsule_id} (via {turn_reference.capsule_id})")
        if constraints:
            print("Constraints:")
            for c in constraints:
                print(f"  - {c.get('id')}: {c.get('result')}")
                evidence_digest = c.get("evidence_digest")
                if evidence_digest:
                    print(f"      evidence_digest: {evidence_digest}")
                    if payload_store is not None:
                        resolved = payload_store.resolve(evidence_digest)
                        if resolved is not None:
                            for line in format_resolved_payload("evidence", resolved):
                                print(line)
        else:
            print("Constraints: (none)")
        print()
        print(build_echo("show", positional=record.capsule_id))
    return 0
