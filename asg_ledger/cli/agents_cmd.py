# SPDX-License-Identifier: Apache-2.0
"""`asg agents --status`: per-agent summary derived from the ledger.

The headline number per agent (``records``) is a real fold evaluation
(the built-in ``actions.count_by_developer/1.0.0`` catalog fold, T1's fold
engine) rather than a number this command computes itself -- per the
workspace's standing rule that "the model never computes evidence; every
numeric output carries a fold envelope or names its record." first/last
seen and the verdict breakdown are read directly off the scanned records
(each one individually visible via `asg log --agent <id>`, i.e. "names its
record" rather than needing its own fold).

There is no ledger-level notion of agent *enrollment* (the Onboarding
design's "path in / capturing / rung" columns) in this package yet -- T2's
ledger only knows about capsules it has actually received, so those columns
are left out here rather than fabricated; see STATUS.md.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter, defaultdict

from ..folds.catalog import Catalog
from ..folds.engine import evaluate_all
from ..ledger.api import ScanQuery
from .constraints_cmd import DEFAULT_CATALOG_DIR
from .format import build_echo, format_envelope_line, format_staleness
from .ledger_io import open_ledger, require_ledger_path

__all__ = ["add_parser", "run"]

COUNT_FOLD_ID = "actions.count_by_developer/1.0.0"


def add_parser(sub: argparse._SubParsersAction) -> argparse.ArgumentParser:
    p = sub.add_parser("agents", help="per-agent summary derived from the ledger")
    p.add_argument("--status", action="store_true", help="show per-agent record counts, first/last seen, verdicts")
    p.add_argument("--ledger", help="ledger store directory or a JSONL fixture file (default: $ASG_LEDGER)")
    p.add_argument("--dir", help="fold catalog directory (default: built-in catalog, or $ASG_FOLD_DIR)")
    p.set_defaults(func=run)
    return p


def run(args: argparse.Namespace) -> int:
    if not args.status:
        print("asg agents: only --status is implemented", file=sys.stderr)
        return 2

    ledger_path = require_ledger_path("agents", args)
    if ledger_path is None:
        return 2

    catalog_dir = args.dir or os.environ.get("ASG_FOLD_DIR") or DEFAULT_CATALOG_DIR
    count_entry = Catalog(catalog_dir).get(COUNT_FOLD_ID)
    if count_entry is None:
        print(f"asg agents: fold {COUNT_FOLD_ID!r} not found in catalog {catalog_dir}", file=sys.stderr)
        return 2

    first_seen: dict[str, str] = {}
    last_seen: dict[str, str] = {}
    verdicts: dict[str, Counter] = defaultdict(Counter)

    with open_ledger(ledger_path) as store:
        capsules = [r.capsule for r in store.scan(ScanQuery())]
        for capsule in capsules:
            agent = capsule.get("developer") or "(unknown)"
            ts = capsule.get("timestamp") or ""
            if agent not in first_seen or ts < first_seen[agent]:
                first_seen[agent] = ts
            if agent not in last_seen or ts > last_seen[agent]:
                last_seen[agent] = ts
            verdict = (capsule.get("disposition") or {}).get("verdict_class") or "(none)"
            verdicts[agent][verdict] += 1

    traces = evaluate_all(count_entry.definition, capsules, staleness_ms=0)

    print(build_echo("agents", flags=[("--status", True)]))
    print()
    for agent in sorted(first_seen):
        trace = traces.get(agent)
        breakdown = " ".join(f"{v}:{n}" for v, n in sorted(verdicts[agent].items()))
        print(agent)
        if trace is not None:
            print(f"  {format_envelope_line(trace.to_envelope())}")
        print(f"  first seen: {first_seen[agent]}")
        print(f"  last seen:  {last_seen[agent]}")
        print(f"  verdicts:   {breakdown}  (see `asg log --agent {agent}` for the records)")
        print()

    print(f"{len(first_seen)} agent(s) · as of {format_staleness(0)}")
    return 0
