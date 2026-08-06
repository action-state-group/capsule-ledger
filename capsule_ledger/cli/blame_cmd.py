# SPDX-License-Identifier: Apache-2.0
"""`capsule blame <target>`: walk a record's ``chain.parent_capsule_id`` links
backward to show what led to it -- the guard decisions and records upstream
of the target, in chain order.

A structural chain walk, not an analysis: it stops at one of four cleanly
classified terminals, reusing the same chain vocabulary the rest of this
codebase already uses (T2's ``ChainGap``, and the upstream
``agent_action_capsule.history`` registry's ``epoch_opens`` relation):

  - standalone   -- the record carries no ``chain`` at all (nothing upstream)
  - epoch_open   -- ``chain.relation == "epoch_opens"``, a legal chain-start
                     per the capsule spec's chain relation registry (never a
                     gap; see that module's ``verify_chain_completeness``)
  - gap          -- ``chain.parent_capsule_id`` doesn't resolve in this ledger
                     (cross-referenced against ``store.find_gaps()`` for the
                     browsable window, same as `capsule log`'s gap reporting)
  - cycle        -- a parent_capsule_id repeats a capsule already walked
                     (defensive; should not occur in a well-formed ledger)
  - truncated    -- ``--max-depth`` was reached before any of the above
"""
from __future__ import annotations

import argparse
import json
import sys

from .format import build_echo, summarize_action
from .ledger_io import open_ledger, require_ledger_path

__all__ = ["add_parser", "run"]


def add_parser(sub: argparse._SubParsersAction) -> argparse.ArgumentParser:
    p = sub.add_parser(
        "blame", help="trace a record back through its chain (parent_capsule_id links) to what led to it"
    )
    p.add_argument("target", help="a capsule_id or an unambiguous prefix")
    p.add_argument("--ledger", help="ledger store directory or a JSONL fixture file (default: $CAPSULE_LEDGER)")
    p.add_argument(
        "--max-depth", dest="max_depth", type=int, default=None, help="stop walking after this many hops"
    )
    p.add_argument("--json", action="store_true", help="print the chain walk as JSON")
    p.set_defaults(func=run)
    return p


def run(args: argparse.Namespace) -> int:
    ledger_path = require_ledger_path("blame", args)
    if ledger_path is None:
        return 2

    with open_ledger(ledger_path) as store:
        record = store.fetch(args.target)
        if record is None:
            print(f"no such capsule {args.target!r} in ledger {ledger_path}", file=sys.stderr)
            return 1

        gaps_by_child = {g.child.capsule_id: g for g in store.find_gaps()}

        hops = [record]
        visited = {record.capsule_id}
        current = record
        terminal_kind = "standalone"
        terminal_detail = None

        while True:
            chain = current.capsule.get("chain") or {}
            parent_id = chain.get("parent_capsule_id")
            relation = chain.get("relation")

            if relation == "epoch_opens":
                terminal_kind, terminal_detail = "epoch_open", parent_id
                break
            if not parent_id:
                terminal_kind, terminal_detail = "standalone", None
                break
            if args.max_depth is not None and len(hops) >= args.max_depth:
                terminal_kind, terminal_detail = "truncated", parent_id
                break
            if parent_id in visited:
                terminal_kind, terminal_detail = "cycle", parent_id
                break

            parent = store.fetch(parent_id)
            if parent is None:
                terminal_kind, terminal_detail = "gap", parent_id
                break

            hops.append(parent)
            visited.add(parent.capsule_id)
            current = parent

    if args.json:
        print(
            json.dumps(
                {
                    "target": args.target,
                    "hops": [
                        {
                            "seq": r.seq,
                            "capsule_id": r.capsule_id,
                            "developer": r.capsule.get("developer"),
                            "verdict": (r.capsule.get("disposition") or {}).get("verdict_class"),
                            "relation": (r.capsule.get("chain") or {}).get("relation"),
                        }
                        for r in hops
                    ],
                    "terminal": {"kind": terminal_kind, "detail": terminal_detail},
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    for i, r in enumerate(hops):
        capsule = r.capsule
        disposition = capsule.get("disposition") or {}
        chain = capsule.get("chain") or {}
        print(f"capsule {r.capsule_id}" + ("  (target)" if i == 0 else ""))
        print(f"  seq:      #{r.seq}")
        print(f"  Agent:    {capsule.get('developer', '')}")
        print(f"  Verdict:  {disposition.get('verdict_class') or '(none)'}")
        print(f"  Date:     {capsule.get('timestamp', '')}")
        print(f"  Action:   {summarize_action(capsule)}")
        if i + 1 < len(hops):
            print(f"  ↑ chain.relation={chain.get('relation')!r}")
        print()

    epoch_open_msg = "epoch boundary reached — chain.relation=epoch_opens is a legal chain-start, not a gap"
    if terminal_detail and terminal_kind == "epoch_open":
        epoch_open_msg += f" (parent_capsule_id={terminal_detail!r} out of scope)"
    labels = {
        "standalone": "root reached — this record carries no chain (standalone)",
        "epoch_open": epoch_open_msg,
        "gap": f"chain gap — parent_capsule_id {terminal_detail!r} not found in this ledger",
        "cycle": f"cycle detected — chain re-visits capsule_id {terminal_detail!r}",
        "truncated": (
            f"walk truncated at --max-depth={args.max_depth} "
            f"(parent_capsule_id={terminal_detail!r} not walked)"
        ),
    }
    print(f"{len(hops)} hop(s) in chain · {labels[terminal_kind]}")

    if terminal_kind == "gap":
        gap = gaps_by_child.get(hops[-1].capsule_id)
        if gap is not None:
            window_line = f"  browsable window: {gap.window}"
            if gap.duration_seconds is not None:
                window_line += f" ({gap.duration_seconds:.3f}s)"
            print(window_line)

    print()
    print(build_echo("blame", positional=args.target))
    return 0
