# SPDX-License-Identifier: Apache-2.0
"""`capsule diff <from-ref> <to-ref>`: a structural set diff between two ledger
checkpoints.

"Epoch" per this package's own upstream dependency (``agent_action_capsule.
history``) is a payload-level concept -- a capsule's ``epoch_id`` plus
``chain.relation == "epoch_opens"`` as the legal chain-start marker for a new
epoch (see that module's ``verify_chain_completeness``). None of this repo's
fixture ledgers carry ``epoch_id`` data, and it is not a concept the ledger
*store* (T2's ``LedgerAPI``) itself knows about -- ``LedgerRecord`` has no
epoch field. So "epoch diff" here is implemented as what `stub_cmds.py`
always said `diff` would be: comparing the ledger's state between two
checkpoints/refs. A *ref* is a seq number, a capsule_id (or unambiguous
prefix), an ISO-8601 timestamp, or the literal ``HEAD`` -- each resolves to a
checkpoint (the highest seq at or before that point). The diff is then a
plain set difference between the two checkpoints' record sets, plus a verdict-
distribution delta and, optionally, a fold-result delta (`--fold`, reusing
T1's fold engine). This is a structural (set/sequence) operation over already-
computed, already-deterministic data -- it draws no new conclusions.
"""
from __future__ import annotations

import argparse
import json
import shlex
import sys
from datetime import datetime

from ..folds.engine import evaluate_one
from ..folds.errors import FoldDeterminismError
from ..ledger.api import ScanQuery
from .fold_ref import catalog_dir, resolve_fold
from .format import format_staleness, format_verdict_label, summarize_action
from .ledger_io import open_ledger, require_ledger_path

__all__ = ["add_parser", "run"]


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _resolve_ref(store, all_records: list, ref: str) -> int | None:
    """Resolve *ref* to a checkpoint seq number, or ``None`` if unresolvable."""
    if ref.upper() == "HEAD":
        return all_records[-1].seq if all_records else 0
    if ref.upper() in ("ROOT", "START", "EMPTY"):
        return 0
    try:
        return int(ref)
    except ValueError:
        pass

    record = store.fetch(ref)
    if record is not None:
        return record.seq

    target_ts = _parse_ts(ref)
    if target_ts is not None:
        seq = 0
        for r in all_records:
            r_ts = _parse_ts(r.capsule.get("timestamp"))
            if r_ts is not None and r_ts <= target_ts:
                seq = max(seq, r.seq)
        return seq

    return None


def _build_echo(args: argparse.Namespace) -> str:
    """`diff` takes two positionals, so it can't reuse `format.build_echo`
    (one positional only) -- same tokenization convention, extended."""
    tokens = ["capsule", "diff", shlex.quote(args.from_ref), shlex.quote(args.to_ref)]
    for fold_ref in args.folds:
        tokens += ["--fold", shlex.quote(fold_ref)]
    if args.key is not None:
        tokens += ["--key", shlex.quote(args.key)]
    return "≡ " + " ".join(tokens)


def _verdict_counts(records: list) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in records:
        v = format_verdict_label(r.capsule.get("disposition") or {})
        counts[v] = counts.get(v, 0) + 1
    return counts


def _is_epoch_boundary(record) -> bool:
    """A record opening a new policy epoch -- ``chain.relation == "epoch_opens"``,
    the same chain vocabulary ``cli/blame_cmd.py`` already treats as a legal
    chain-start (``agent_action_capsule.history``'s registry), never a gap.
    Today the only producer of this relation is a policy-manifest activation
    (``capsule_ledger.policy.build_manifest_activation_capsule``), but the check
    itself is generic to the relation, not hardcoded to that one event."""
    return ((record.capsule.get("chain") or {}).get("relation")) == "epoch_opens"


def _boundary_line(record) -> str:
    detail = (record.capsule.get("asg_payload") or {}).get("detail") or {}
    manifest_digest = detail.get("manifest_digest", "?")
    manifest_id = detail.get("manifest_id", "?")
    return (
        f"  ◆ capsule {record.capsule_id[:16]}  manifest {manifest_id}  "
        f"{manifest_digest[:16]}…  {record.capsule.get('developer', '')}"
    )


def add_parser(sub: argparse._SubParsersAction) -> argparse.ArgumentParser:
    p = sub.add_parser(
        "diff", help="compare the ledger's state between two checkpoints/refs (structural set diff)"
    )
    p.add_argument(
        "from_ref", help="checkpoint ref: seq number, capsule_id (or prefix), ISO-8601 timestamp, or HEAD"
    )
    p.add_argument("to_ref", nargs="?", default="HEAD", help="checkpoint ref (default: HEAD)")
    p.add_argument("--ledger", help="ledger store directory or a JSONL fixture file (default: $CAPSULE_LEDGER)")
    p.add_argument(
        "--fold", dest="folds", action="append", default=[],
        help="fold_id, definition_digest, or path to a definition YAML file -- diff its cumulative "
        "result between the two checkpoints (repeatable)",
    )
    p.add_argument("--dir", help="fold catalog directory (default: built-in catalog, or $CAPSULE_FOLD_DIR)")
    p.add_argument("--key", help="fold group key value (only meaningful with --fold)")
    p.add_argument("--json", action="store_true", help="print the diff as JSON")
    p.set_defaults(func=run)
    return p


def _fold_delta(fold_ref: str, args: argparse.Namespace, state_from: list, state_to: list) -> tuple | None:
    directory = catalog_dir(args)
    definition = resolve_fold(fold_ref, directory)
    if definition is None:
        print(f"capsule diff: no such fold {fold_ref!r} in catalog {directory}", file=sys.stderr)
        return None

    capsules_from = [r.capsule for r in state_from]
    capsules_to = [r.capsule for r in state_to]
    as_of_from = capsules_from[-1].get("timestamp") if capsules_from else None
    as_of_to = capsules_to[-1].get("timestamp") if capsules_to else None

    try:
        trace_from = evaluate_one(definition, capsules_from, key_value=args.key, as_of=as_of_from)
        trace_to = evaluate_one(definition, capsules_to, key_value=args.key, as_of=as_of_to)
    except FoldDeterminismError as exc:
        print(f"capsule diff: fold {fold_ref!r}: {exc}", file=sys.stderr)
        return None

    return definition.fold_id, trace_from.result, trace_to.result


def run(args: argparse.Namespace) -> int:
    ledger_path = require_ledger_path("diff", args)
    if ledger_path is None:
        return 2

    with open_ledger(ledger_path) as store:
        all_records = list(store.scan(ScanQuery()))
        seq_from = _resolve_ref(store, all_records, args.from_ref)
        seq_to = _resolve_ref(store, all_records, args.to_ref)
        if seq_from is None or seq_to is None:
            bad = args.from_ref if seq_from is None else args.to_ref
            print(
                f"capsule diff: cannot resolve ref {bad!r} (not a seq number, capsule_id, "
                "ISO-8601 timestamp, or HEAD)",
                file=sys.stderr,
            )
            return 2

        state_from = [r for r in all_records if r.seq <= seq_from]
        state_to = [r for r in all_records if r.seq <= seq_to]
        ids_from = {r.capsule_id for r in state_from}
        ids_to = {r.capsule_id for r in state_to}

        added = [r for r in state_to if r.capsule_id not in ids_from]
        removed = [r for r in state_from if r.capsule_id not in ids_to]

        # Manifest activations (and any future epoch_opens producer) are a
        # policy boundary, not an ordinary decision -- pulled out of the
        # plain added-record count so a manifest change is never silently
        # absorbed into "N new record(s)".
        boundaries = [r for r in added if _is_epoch_boundary(r)]
        added = [r for r in added if not _is_epoch_boundary(r)]

        counts_from = _verdict_counts(state_from)
        counts_to = _verdict_counts(state_to)
        verdict_keys = sorted(set(counts_from) | set(counts_to))
        verdict_delta = {
            k: (counts_from.get(k, 0), counts_to.get(k, 0))
            for k in verdict_keys
            if counts_from.get(k, 0) != counts_to.get(k, 0)
        }

        fold_deltas = []
        for fold_ref in args.folds:
            result = _fold_delta(fold_ref, args, state_from, state_to)
            if result is None:
                return 1
            fold_deltas.append(result)

    if args.json:
        print(
            json.dumps(
                {
                    "from": {"ref": args.from_ref, "checkpoint": seq_from},
                    "to": {"ref": args.to_ref, "checkpoint": seq_to},
                    "added": [r.capsule_id for r in added],
                    "removed": [r.capsule_id for r in removed],
                    "manifest_boundaries": [
                        {
                            "capsule_id": r.capsule_id,
                            "manifest_id": ((r.capsule.get("asg_payload") or {}).get("detail") or {}).get("manifest_id"),
                            "manifest_digest": ((r.capsule.get("asg_payload") or {}).get("detail") or {}).get(
                                "manifest_digest"
                            ),
                        }
                        for r in boundaries
                    ],
                    "verdict_delta": {k: {"from": v[0], "to": v[1]} for k, v in verdict_delta.items()},
                    "fold_deltas": [
                        {"fold_id": fid, "from": r_from, "to": r_to} for fid, r_from, r_to in fold_deltas
                    ],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    print(
        f"capsule diff: checkpoint #{seq_from} ({args.from_ref}) → checkpoint #{seq_to} ({args.to_ref})"
    )
    print()

    if boundaries:
        print(f"{len(boundaries)} manifest boundary event(s):")
        for r in boundaries:
            print(_boundary_line(r))
        print()

    if not added and not removed and not boundaries:
        print("no new or removed records between these checkpoints")
    else:
        if added:
            print(f"{len(added)} new record(s):")
            for r in added:
                capsule = r.capsule
                disposition = capsule.get("disposition") or {}
                print(
                    f"  + capsule {r.capsule_id[:16]}  {format_verdict_label(disposition):<10}  "
                    f"{capsule.get('developer', ''):<24}  {summarize_action(capsule)}"
                )
        if removed:
            print(f"{len(removed)} record(s) only in {args.from_ref} (not reachable from {args.to_ref}):")
            for r in removed:
                capsule = r.capsule
                disposition = capsule.get("disposition") or {}
                print(
                    f"  - capsule {r.capsule_id[:16]}  {format_verdict_label(disposition):<10}  "
                    f"{capsule.get('developer', ''):<24}  {summarize_action(capsule)}"
                )
    print()

    if verdict_delta:
        print("verdict distribution delta:")
        for k, (before, after) in verdict_delta.items():
            sign = "+" if after >= before else ""
            print(f"  {k}: {before} → {after} ({sign}{after - before})")
    else:
        print("verdict distribution: unchanged")
    print()

    if fold_deltas:
        print("fold deltas:")
        for fold_id, result_from, result_to in fold_deltas:
            print(f"  {fold_id}: {result_from} → {result_to}")
        print()

    print(f"as of {format_staleness(0)}")
    print()
    print(_build_echo(args))
    return 0
