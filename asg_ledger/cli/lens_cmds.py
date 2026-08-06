# SPDX-License-Identifier: Apache-2.0
"""`capsule lens` verbs: structural lenses over the ledger query API
(T2's ``LedgerAPI.scan``) -- read-only analysis views, not evidence
artifacts, following ``fold_cmds.py``'s per-verb-group module convention
so ``main.py`` stays a thin dispatcher.

Each lens is a set/sequence operation over already-recorded, already-
verified data -- counting, windowing, and pattern-matching on IDs,
verbs, and timestamps. None of them perform natural-language
understanding or inference about intent; see each lens module under
``asg_ledger/lenses/`` for its exact structural definition:

  - `lens novelty`       -- ``lenses.novelty``
  - `lens shape`          -- ``lenses.shape`` (retry storms + A<->B cycles)
  - `lens blast-radius`   -- ``lenses.blast_radius`` (forward chain walk,
                              the counterpart to `capsule blame`'s backward walk)
"""
from __future__ import annotations

import argparse
import json
import sys

from ..folds.duration import parse_duration_seconds
from ..ledger.api import ScanQuery
from ..lenses import compute_blast_radius, find_cycles, find_novel_records, find_retry_storms
from .format import build_echo
from .ledger_io import open_ledger, require_ledger_path

__all__ = ["add_parser"]


def _cmd_lens_novelty(args: argparse.Namespace) -> int:
    ledger_path = require_ledger_path("lens novelty", args)
    if ledger_path is None:
        return 2

    with open_ledger(ledger_path) as store:
        query = ScanQuery(agent=args.agent) if args.agent else ScanQuery()
        records = list(store.scan(query))
        findings = find_novel_records(records, min_history=args.min_history)

    if args.json:
        print(
            json.dumps(
                {
                    "findings": [
                        {
                            "seq": f.record.seq,
                            "capsule_id": f.record.capsule_id,
                            "developer": f.record.capsule.get("developer"),
                            "verb": f.verb,
                            "prior_verbs": sorted(f.prior_verbs),
                        }
                        for f in findings
                    ],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if not findings:
        print("no novel actions found (every verb seen for its agent has occurred before)")
    else:
        print(f"{len(findings)} novel action(s):")
        for f in findings:
            capsule = f.record.capsule
            prior = ", ".join(sorted(f.prior_verbs)) or "(none)"
            print(
                f"  capsule {f.record.capsule_id[:16]}  seq #{f.record.seq}  "
                f"{capsule.get('developer', ''):<24}  verb={f.verb!r}  "
                f"(never seen before for this agent; prior verbs: {prior})"
            )
    print()
    print(build_echo("lens novelty", flags=[("--agent", args.agent), ("--min-history", args.min_history)]))
    return 0


def _cmd_lens_shape(args: argparse.Namespace) -> int:
    ledger_path = require_ledger_path("lens shape", args)
    if ledger_path is None:
        return 2

    try:
        parse_duration_seconds(args.window)
    except ValueError as exc:
        print(f"capsule lens shape: {exc}", file=sys.stderr)
        return 2

    with open_ledger(ledger_path) as store:
        query = ScanQuery(agent=args.agent) if args.agent else ScanQuery()
        records = list(store.scan(query))
        storms = find_retry_storms(records, min_repeats=args.min_repeats, window=args.window)
        cycles = find_cycles(records, min_length=args.min_cycle_length)

    if args.json:
        print(
            json.dumps(
                {
                    "retry_storms": [
                        {
                            "developer": s.developer,
                            "verb": s.verb,
                            "capsule_ids": [r.capsule_id for r in s.records],
                            "span_seconds": s.span_seconds,
                        }
                        for s in storms
                    ],
                    "cycles": [
                        {
                            "developer": c.developer,
                            "verbs": list(c.verbs),
                            "capsule_ids": [r.capsule_id for r in c.records],
                        }
                        for c in cycles
                    ],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if not storms and not cycles:
        print("no retry storms or cyclic patterns found")
    else:
        if storms:
            print(f"{len(storms)} retry storm(s):")
            for s in storms:
                span = f"{s.span_seconds:.3f}s" if s.span_seconds is not None else "(unknown span)"
                print(
                    f"  {s.developer:<24}  verb={s.verb!r}  {len(s.records)}x in {span}  "
                    f"(seq #{s.records[0].seq}–#{s.records[-1].seq})"
                )
            print()
        if cycles:
            print(f"{len(cycles)} cyclic pattern(s):")
            for c in cycles:
                a, b = c.verbs
                print(
                    f"  {c.developer:<24}  {a!r} <-> {b!r}  {len(c.records)}x  "
                    f"(seq #{c.records[0].seq}–#{c.records[-1].seq})"
                )
            print()
    print(
        build_echo(
            "lens shape",
            flags=[
                ("--agent", args.agent),
                ("--min-repeats", args.min_repeats),
                ("--window", args.window),
                ("--min-cycle-length", args.min_cycle_length),
            ],
        )
    )
    return 0


def _cmd_lens_blast_radius(args: argparse.Namespace) -> int:
    ledger_path = require_ledger_path("lens blast-radius", args)
    if ledger_path is None:
        return 2

    with open_ledger(ledger_path) as store:
        target = store.fetch(args.target)
        if target is None:
            print(f"no such capsule {args.target!r} in ledger {ledger_path}", file=sys.stderr)
            return 1
        records = list(store.scan(ScanQuery()))
        result = compute_blast_radius(records, target)

    if args.json:
        print(
            json.dumps(
                {
                    "target": result.target.capsule_id,
                    "count": result.count,
                    "downstream": [
                        {"seq": r.seq, "capsule_id": r.capsule_id, "developer": r.capsule.get("developer")}
                        for r in result.downstream
                    ],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    print(f"capsule {result.target.capsule_id}")
    print(f"  seq: #{result.target.seq}")
    print()
    if result.count == 0:
        print("blast radius: 0 downstream record(s) cite this capsule")
    else:
        print(f"blast radius: {result.count} downstream record(s) cite this capsule (directly or transitively):")
        for r in result.downstream:
            capsule = r.capsule
            chain = capsule.get("chain") or {}
            parent = chain.get("parent_capsule_id") or ""
            print(
                f"  capsule {r.capsule_id[:16]}  seq #{r.seq}  {capsule.get('developer', ''):<24}  "
                f"chain.relation={chain.get('relation')!r}  parent={parent[:16]}"
            )
    print()
    print(build_echo("lens blast-radius", positional=args.target))
    return 0


def add_parser(sub: argparse._SubParsersAction) -> argparse.ArgumentParser:
    lens = sub.add_parser(
        "lens", help="structural lenses over the query API: novelty, shape (retry storms/cycles), blast-radius"
    )
    lens_sub = lens.add_subparsers(dest="lens_command")
    lens.set_defaults(lens_parser=lens)

    p_novelty = lens_sub.add_parser(
        "novelty", help="flag records whose action verb has never occurred before for that record's own agent"
    )
    p_novelty.add_argument("--ledger", help="ledger store directory or a JSONL fixture file (default: $ASG_LEDGER)")
    p_novelty.add_argument("--agent", help="restrict the scan to this agent (developer) only")
    p_novelty.add_argument(
        "--min-history", dest="min_history", type=int, default=1,
        help="an agent's first N record(s) are never judged -- no baseline exists yet (default: 1)",
    )
    p_novelty.add_argument("--json", action="store_true", help="print findings as JSON")
    p_novelty.set_defaults(func=_cmd_lens_novelty)

    p_shape = lens_sub.add_parser(
        "shape", help="detect retry storms (repeated near-identical actions) and A<->B cyclic patterns per agent"
    )
    p_shape.add_argument("--ledger", help="ledger store directory or a JSONL fixture file (default: $ASG_LEDGER)")
    p_shape.add_argument("--agent", help="restrict the scan to this agent (developer) only")
    p_shape.add_argument(
        "--min-repeats", dest="min_repeats", type=int, default=3,
        help="minimum consecutive same-verb records (per agent) to call a retry storm (default: 3)",
    )
    p_shape.add_argument(
        "--window", default="60s",
        help="max timestamp span across a retry storm's records, e.g. '60s', '5m' (default: 60s)",
    )
    p_shape.add_argument(
        "--min-cycle-length", dest="min_cycle_length", type=int, default=4,
        help="minimum records in an alternating A<->B run to call it a cycle (default: 4, i.e. A,B,A,B)",
    )
    p_shape.add_argument("--json", action="store_true", help="print findings as JSON")
    p_shape.set_defaults(func=_cmd_lens_shape)

    p_blast = lens_sub.add_parser(
        "blast-radius", help="count downstream records that cite a target (directly or transitively) via chain links"
    )
    p_blast.add_argument("target", help="a capsule_id or an unambiguous prefix")
    p_blast.add_argument("--ledger", help="ledger store directory or a JSONL fixture file (default: $ASG_LEDGER)")
    p_blast.add_argument("--json", action="store_true", help="print the result as JSON")
    p_blast.set_defaults(func=_cmd_lens_blast_radius)

    return lens
