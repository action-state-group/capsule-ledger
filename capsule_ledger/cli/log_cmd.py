# SPDX-License-Identifier: Apache-2.0
"""`capsule log`: git-log-style listing over the ledger query API (T2's ScanQuery)."""
from __future__ import annotations

import argparse

from ..ledger.api import ScanQuery
from .format import build_echo, format_staleness, format_verdict, summarize_action
from .ledger_io import add_scan_query_args, build_scan_query, echo_parts, open_ledger, require_ledger_path

__all__ = ["add_parser", "run"]


def add_parser(sub: argparse._SubParsersAction) -> argparse.ArgumentParser:
    p = sub.add_parser("log", help="list ledger records matching a filter (git-log style)")
    add_scan_query_args(p)
    p.set_defaults(func=run)
    return p


def run(args: argparse.Namespace) -> int:
    ledger_path = require_ledger_path("log", args)
    if ledger_path is None:
        return 2

    print(build_echo("log", flags=echo_parts(args)))
    print()

    query = build_scan_query(args)
    shown = 0
    with open_ledger(ledger_path) as store:
        total = sum(1 for _ in store.scan(ScanQuery()))
        for record in store.scan(query):
            shown += 1
            capsule = record.capsule
            disposition = capsule.get("disposition") or {}
            print(f"capsule {record.capsule_id}")
            print(f"Agent:    {capsule.get('developer', '')}")
            print(f"Operator: {capsule.get('operator', '')}")
            print(f"Verdict:  {format_verdict(disposition)}")
            print(f"Date:     {capsule.get('timestamp', '')}")
            print()
            print(f"    {summarize_action(capsule)}")
            print()
        gaps = store.find_gaps()

    sequence_note = "sequence unbroken" if not gaps else f"{len(gaps)} chain gap(s) detected"
    print(
        f"{shown} of {total} records shown (filtered view — the ledger itself is never filtered) · "
        f"{sequence_note} · as of {format_staleness(0)}"
    )
    return 0
