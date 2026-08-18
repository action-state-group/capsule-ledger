# SPDX-License-Identifier: Apache-2.0
"""Shared plumbing every ledger-backed verb (log/show/verify/bundle/agents) uses:
opening a ledger from a CLI argument, the common filter-flag set, and the
``ScanQuery`` it builds.

``--ledger`` accepts either a real :class:`~capsule_ledger.ledger.store.LedgerStore`
root (a directory) or a plain JSONL fixture file (imported into an ephemeral,
throwaway store for the duration of the command) -- the same convenience
``fold test`` already offers via its own ``--ledger`` flag, extended here to
every query-API verb so the fixture ledgers under ``tests/fixtures/`` work
directly with no separate "build a store" step.
"""
from __future__ import annotations

import argparse
import contextlib
import os
import shutil
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

from ..envcompat import env_get
from ..ledger import LedgerStore
from ..ledger.api import ScanQuery
from ..payload_store import PayloadStore

__all__ = [
    "open_ledger",
    "require_ledger_path",
    "add_scan_query_args",
    "build_scan_query",
    "echo_parts",
    "local_payload_store",
]


@contextlib.contextmanager
def open_ledger(path: str | os.PathLike) -> Iterator[LedgerStore]:
    p = Path(path)
    if p.is_dir():
        store = LedgerStore(p)
        try:
            yield store
        finally:
            store.close()
        return

    tmp_root = Path(tempfile.mkdtemp(prefix="capsule-ledger-cli-"))
    store = LedgerStore(tmp_root)
    try:
        store.import_jsonl(p)
        yield store
    finally:
        store.close()
        shutil.rmtree(tmp_root, ignore_errors=True)


def local_payload_store(ledger_path: str | os.PathLike) -> PayloadStore | None:
    """The resolve-at-read gate (item 5a): auto-resolve applies only on a
    LOCAL, standalone-grade ledger with a payload store actually present --
    never on an imported JSONL fixture or a foreign bundle, which
    ``open_ledger()`` opens into a throwaway tempdir with no lasting home
    for one. Returns ``None`` (never a store you'd have to remember to
    check ``.exists`` on) unless both conditions hold."""
    root = Path(ledger_path)
    if not root.is_dir():
        return None
    store = PayloadStore(root)
    return store if store.exists else None


def require_ledger_path(verb: str, args: argparse.Namespace) -> str | None:
    """Resolve ``--ledger`` (or ``$CAPSULE_LEDGER``, or legacy ``$ASG_LEDGER``);
    prints a usage error and returns ``None`` rather than raising, so callers
    can return a clean exit code instead of an uncaught ``SystemExit``."""
    path = getattr(args, "ledger", None) or env_get("CAPSULE_LEDGER", "ASG_LEDGER")
    if path is None:
        print(f"capsule {verb}: --ledger is required (or set $CAPSULE_LEDGER)", file=sys.stderr)
    return path


def add_scan_query_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--ledger", help="ledger store directory or a JSONL fixture file (default: $CAPSULE_LEDGER)")
    parser.add_argument("--agent", help="filter: developer/agent id (ScanQuery.agent)")
    parser.add_argument("--since", help="filter: inclusive lower timestamp bound (ISO-8601)")
    parser.add_argument("--until", help="filter: inclusive upper timestamp bound (ISO-8601)")
    parser.add_argument("--counterparty", help="filter: operator (ScanQuery.counterparty)")
    parser.add_argument("--verdict", help="filter: disposition.verdict_class")
    parser.add_argument("--action-type", dest="action_type", help="filter: action_type")
    parser.add_argument("--limit", type=int, help="filter: maximum records returned")


def build_scan_query(args: argparse.Namespace) -> ScanQuery:
    return ScanQuery(
        agent=args.agent,
        since=args.since,
        until=args.until,
        counterparty=args.counterparty,
        verdict=args.verdict,
        action_type=args.action_type,
        limit=args.limit,
    )


def echo_parts(args: argparse.Namespace) -> list[tuple[str, object]]:
    """The filter flags in their fixed CLI-echo order."""
    return [
        ("--agent", args.agent),
        ("--since", args.since),
        ("--until", args.until),
        ("--counterparty", args.counterparty),
        ("--verdict", args.verdict),
        ("--action-type", args.action_type),
        ("--limit", args.limit),
    ]
