# SPDX-License-Identifier: Apache-2.0
"""``capsule thresholds propose``: fold a pack's proposer(s) over observed
traffic, output proposed caps with rationale. Deterministic given the
ledger; never enforced by this command itself -- see ``packs/thresholds.py``.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..packs import PackDefinitionError, load_pack_dir
from ..packs.thresholds import propose_thresholds, write_proposals_file
from .init_cmds import BUILTIN_PACK_CATALOG_DIR
from .ledger_io import open_ledger

__all__ = ["add_parser"]


def _cmd_thresholds_propose(args: argparse.Namespace) -> int:
    catalog_dir = Path(args.pack_catalog_dir) if args.pack_catalog_dir else BUILTIN_PACK_CATALOG_DIR
    pack_dir = catalog_dir / args.pack
    try:
        pack = load_pack_dir(pack_dir)
    except PackDefinitionError as exc:
        print(f"capsule thresholds propose: pack {args.pack!r} failed to load ({exc.reason}): {exc}", file=sys.stderr)
        return 1

    if not pack.proposers:
        print(f"capsule thresholds propose: pack {pack.pack_id!r} declares no proposers in 'proposers'", file=sys.stderr)
        return 1

    with open_ledger(args.ledger) as store:
        records = [r.capsule for r in store.scan()]

    if not records:
        print(f"capsule thresholds propose: {args.ledger} has no records to fold over", file=sys.stderr)
        return 1

    action_classes = sorted({a.action_class for a in pack.action_semantics})
    proposals = []
    for action_class in action_classes:
        for fold in pack.folds:
            if not any(p.fold_id == fold.fold_id for p in pack.proposers):
                continue
            proposal = propose_thresholds(pack, fold, records, action_class=action_class, percentile=args.percentile)
            proposals.append(proposal)

    if not proposals:
        print("capsule thresholds propose: no proposer matched any of this pack's folds", file=sys.stderr)
        return 1

    print(f"proposals for {pack.pack_id} (percentile={args.percentile}, {len(records)} record(s) folded):")
    for p in proposals:
        print(f"  {p.action_class}: proposed_cap_minor={p.proposed_cap_minor}")
        print(f"    rationale: {p.rationale}")

    if args.out:
        write_proposals_file(args.out, pack, proposals)
        print(f"wrote {args.out}")

    return 0


def add_parser(sub: argparse._SubParsersAction) -> argparse.ArgumentParser:
    thresholds = sub.add_parser("thresholds", help="threshold proposers: fold observed traffic into proposed caps")
    thresholds_sub = thresholds.add_subparsers(dest="thresholds_command")
    thresholds.set_defaults(thresholds_parser=thresholds)

    p_propose = thresholds_sub.add_parser(
        "propose", help="fold a pack's proposer(s) over a ledger's observed traffic, output proposed caps"
    )
    p_propose.add_argument("--pack", required=True, help="pack name, e.g. payments-safety (built-in catalog)")
    p_propose.add_argument(
        "--pack-catalog-dir", default=None, help="override the built-in pack catalog directory (mainly for tests)"
    )
    p_propose.add_argument("--ledger", required=True, help="ledger store directory or a JSONL fixture file to fold over")
    p_propose.add_argument(
        "--percentile", type=int, default=95, help="percentile of the observed distribution to propose (default: 95)"
    )
    p_propose.add_argument("--out", default=None, help="write proposals to this YAML file (for report --proposals / enforce --proposals)")
    p_propose.set_defaults(func=_cmd_thresholds_propose)

    return thresholds
