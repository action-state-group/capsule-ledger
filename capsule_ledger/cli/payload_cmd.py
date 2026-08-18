# SPDX-License-Identifier: Apache-2.0
"""`capsule payload put`: deliberately load a raw JSON payload into this
ledger's local resolve-at-read store (``payload_store.py``), keyed by its
own content digest.

This is the one deliberate act that populates the store -- nothing else in
this package ever writes to it. A reader runs this because they legitimately
hold a preimage a capsule only committed by digest (their own evidence log,
their own guard's pre-digest record of a ``reason``/``evidence`` object) and
wants `capsule show`/`capsule log`/the local console to resolve it back onto
the matching ``evidence_digest``/``reason_digest`` at display time.

Requires a real ledger DIRECTORY, never a JSONL fixture path -- the payload
store is rooted at ``<ledger_root>/payloads/`` (a real, persistent
``LedgerStore`` directory), which is also what makes "never on
imported/foreign bundles" true by construction: an imported fixture is
opened into a throwaway tempdir with no lasting home for a payload store.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..payload_store import PayloadStore
from .ledger_io import require_ledger_path

__all__ = ["add_parser", "run_put"]


def add_parser(sub: argparse._SubParsersAction) -> argparse.ArgumentParser:
    p = sub.add_parser("payload", help="manage this ledger's local resolve-at-read payload store")
    payload_sub = p.add_subparsers(dest="payload_command")

    put = payload_sub.add_parser(
        "put", help="store a raw JSON payload locally, keyed by its own digest, for resolve-at-read"
    )
    put.add_argument("file", help="a JSON file holding the payload you legitimately hold the preimage for")
    put.add_argument(
        "--ledger",
        help="ledger store DIRECTORY (default: $CAPSULE_LEDGER) -- must be a real local ledger, not a JSONL fixture",
    )
    put.set_defaults(func=run_put)

    p.set_defaults(payload_parser=p, payload_command=None)
    return p


def run_put(args: argparse.Namespace) -> int:
    ledger_path = require_ledger_path("payload put", args)
    if ledger_path is None:
        return 2

    root = Path(ledger_path)
    if not root.is_dir():
        print(
            f"capsule payload put: --ledger must be a real ledger directory (got a file: {root}) -- "
            "the resolve-at-read payload store only exists for a local, standalone ledger you actually "
            "hold, never for an imported JSONL fixture or a foreign bundle",
            file=sys.stderr,
        )
        return 2

    source = Path(args.file)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"capsule payload put: could not read {source} as JSON: {exc}", file=sys.stderr)
        return 2

    digest = PayloadStore(root).put(payload)
    print(f"stored {source} -> {digest}")
    print(
        "resolved automatically wherever this digest appears in this ledger's records "
        "(capsule show / capsule log / capsule console) -- never exported, never bundled"
    )
    return 0
