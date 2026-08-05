# SPDX-License-Identifier: Apache-2.0
"""`asg bisect`: find the first record in ledger order where a condition
becomes true -- a sequence search, git-bisect's search pattern applied to
ledger records instead of commits.

Deliberately NOT an unguarded binary search. Git bisect's O(log n) halving is
only correct when the predicate is monotonic across the search range (once
bad, always bad); this tool has no way to guarantee that in general. A
verdict can flip back and forth across a ledger, and a rolling-window fold
(e.g. ``spend.weekly``) can *decrease* as older matches roll out of the
window, so "first record where the cumulative fold exceeds X" is not
provably monotonic either. An unguarded bisection over a non-monotonic
predicate would silently return the wrong "first" record -- a correctness
bug in a tool whose whole purpose is being trustworthy about that first
record. So this scans forward in ledger order (spec-mandated order for fold
replay too, per the fold engine's own determinism rule 3) and returns the
first true index -- always correct regardless of monotonicity, and at the
ledger sizes this tool targets, the O(n) cost is not a real tradeoff.
"""
from __future__ import annotations

import argparse
import json
import sys

from ..folds.engine import evaluate_one
from ..folds.errors import FoldDeterminismError
from ..ledger.api import ScanQuery
from .fold_ref import catalog_dir, resolve_fold
from .format import build_echo, summarize_action
from .ledger_io import open_ledger, require_ledger_path

__all__ = ["add_parser", "run"]

_FOLD_OPS = {
    "gt": lambda v, t: v > t,
    "gte": lambda v, t: v >= t,
    "lt": lambda v, t: v < t,
    "lte": lambda v, t: v <= t,
}


def add_parser(sub: argparse._SubParsersAction) -> argparse.ArgumentParser:
    p = sub.add_parser(
        "bisect", help="find the first record in ledger order where a condition becomes true"
    )
    p.add_argument("--ledger", help="ledger store directory or a JSONL fixture file (default: $ASG_LEDGER)")
    condition = p.add_mutually_exclusive_group(required=True)
    condition.add_argument(
        "--verdict", help="condition: this record's disposition.verdict_class equals VALUE"
    )
    condition.add_argument(
        "--fold", dest="fold_ref",
        help="condition: a fold_id/definition_digest/path whose cumulative result (over records up to "
        "and including this one) satisfies --gt/--gte/--lt/--lte THRESHOLD",
    )
    op = p.add_mutually_exclusive_group()
    op.add_argument("--gt", type=int)
    op.add_argument("--gte", type=int)
    op.add_argument("--lt", type=int)
    op.add_argument("--lte", type=int)
    p.add_argument("--key", help="fold group key value (only meaningful with --fold)")
    p.add_argument("--dir", help="fold catalog directory (default: built-in catalog, or $ASG_FOLD_DIR)")
    p.add_argument("--json", action="store_true", help="print the result as JSON")
    p.set_defaults(func=run)
    return p


def _resolve_threshold(args: argparse.Namespace) -> tuple[str, int] | None:
    for op in ("gt", "gte", "lt", "lte"):
        value = getattr(args, op, None)
        if value is not None:
            return op, value
    return None


def _echo_flags(args: argparse.Namespace) -> list[tuple[str, object]]:
    flags: list[tuple[str, object]] = [("--verdict", args.verdict), ("--fold", args.fold_ref)]
    for op in ("gt", "gte", "lt", "lte"):
        flags.append((f"--{op}", getattr(args, op, None)))
    flags.append(("--key", args.key))
    return flags


def run(args: argparse.Namespace) -> int:
    ledger_path = require_ledger_path("bisect", args)
    if ledger_path is None:
        return 2

    if args.fold_ref is not None:
        threshold = _resolve_threshold(args)
        if threshold is None:
            print("asg bisect: --fold requires one of --gt/--gte/--lt/--lte", file=sys.stderr)
            return 2

    with open_ledger(ledger_path) as store:
        records = list(store.scan(ScanQuery()))

        found = None
        if args.verdict is not None:
            for r in records:
                verdict = (r.capsule.get("disposition") or {}).get("verdict_class")
                if verdict == args.verdict:
                    found = r
                    break
            description = f"disposition.verdict_class == {args.verdict!r}"
        else:
            op, threshold_value = threshold
            directory = catalog_dir(args)
            definition = resolve_fold(args.fold_ref, directory)
            if definition is None:
                print(f"asg bisect: no such fold {args.fold_ref!r} in catalog {directory}", file=sys.stderr)
                return 2

            capsules: list[dict] = []
            for r in records:
                capsules.append(r.capsule)
                as_of = r.capsule.get("timestamp")
                try:
                    trace = evaluate_one(definition, capsules, key_value=args.key, as_of=as_of)
                except FoldDeterminismError as exc:
                    print(f"asg bisect: fold {args.fold_ref!r}: {exc}", file=sys.stderr)
                    return 1
                result = trace.result
                if not isinstance(result, int) or isinstance(result, bool):
                    print(
                        f"asg bisect: fold {args.fold_ref!r} result {result!r} is not comparable "
                        f"with --{op}",
                        file=sys.stderr,
                    )
                    return 1
                if _FOLD_OPS[op](result, threshold_value):
                    found = r
                    break
            description = f"{definition.fold_id} {op} {threshold_value}"

    if args.json:
        print(
            json.dumps(
                {
                    "condition": description,
                    "matched": found is not None,
                    "record": (
                        {
                            "seq": found.seq,
                            "capsule_id": found.capsule_id,
                            "capsule": found.capsule,
                        }
                        if found is not None
                        else None
                    ),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if found is not None else 1

    if found is None:
        print(f"asg bisect: no record in this ledger satisfies: {description}", file=sys.stderr)
        return 1

    capsule = found.capsule
    disposition = capsule.get("disposition") or {}
    print(f"first record where {description}:")
    print()
    print(f"capsule {found.capsule_id}")
    print(f"  seq:      #{found.seq} (of {len(records)})")
    print(f"  Agent:    {capsule.get('developer', '')}")
    print(f"  Verdict:  {disposition.get('verdict_class') or '(none)'}")
    print(f"  Date:     {capsule.get('timestamp', '')}")
    print(f"  Action:   {summarize_action(capsule)}")
    print()
    print(build_echo("bisect", flags=_echo_flags(args)))
    return 0
