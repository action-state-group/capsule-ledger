# SPDX-License-Identifier: Apache-2.0
"""Data-shaping functions for the local console server (`capsule console`).

Pure functions over a real :class:`~asg_ledger.ledger.api.LedgerAPI` -- no
HTTP, no server state -- so they're exercisable directly in tests without a
socket. ``server.py`` is the thin HTTP wiring on top of this module. Every
field returned here comes straight off a real capsule, a real
``store.verify()`` result, or a real fold replay -- nothing is invented for
display.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..cli.format import build_echo, format_envelope_line, format_staleness, summarize_action
from ..folds import Catalog, FoldDeterminismError, evaluate_one
from ..ledger.api import LedgerAPI, ScanQuery
from ..ledger.records import LedgerRecord

__all__ = [
    "checkpoint_status",
    "list_records",
    "record_detail",
    "record_summary",
]

DEFAULT_CATALOG_DIR = Path(__file__).resolve().parent.parent / "folds" / "catalog_defs"


def _fold_catalog_dir() -> Path:
    env = os.environ.get("ASG_FOLD_DIR")
    return Path(env) if env else DEFAULT_CATALOG_DIR


def _fingerprint(capsule_id: str) -> str:
    return capsule_id[:8] + "…" if capsule_id else ""


def checkpoint_status(store: LedgerAPI) -> dict[str, Any]:
    """The console's freshness status line: "checkpoint #N · as of <age> ·
    verifies offline" -- always computed from a fresh re-scan, never cached,
    so its own age is always ~0 (the same convention `capsule log`'s own
    trailing status line already uses -- see `cli/log_cmd.py`)."""
    total = sum(1 for _ in store.scan(ScanQuery()))
    staleness_label = format_staleness(0)
    return {
        "checkpoint": total,
        "staleness_label": staleness_label,
        "line": f"checkpoint #{total} · as of {staleness_label} · verifies offline",
    }


def record_summary(record: LedgerRecord) -> dict[str, Any]:
    capsule = record.capsule
    return {
        "capsule_id": record.capsule_id,
        "fingerprint": _fingerprint(record.capsule_id),
        "seq": record.seq,
        "agent": capsule.get("developer", ""),
        "operator": capsule.get("operator", ""),
        "action": summarize_action(capsule),
        "action_type": capsule.get("action_type", ""),
        "timestamp": capsule.get("timestamp", ""),
        "disposition": capsule.get("disposition") or {},
        "assurance": capsule.get("assurance") or {},
    }


def _echo_parts(filters: dict[str, Any]) -> list[tuple[str, object]]:
    return [
        ("--agent", filters.get("agent")),
        ("--since", filters.get("since")),
        ("--until", filters.get("until")),
        ("--counterparty", filters.get("counterparty")),
        ("--verdict", filters.get("verdict")),
        ("--action-type", filters.get("action_type")),
        ("--limit", filters.get("limit")),
    ]


def list_records(store: LedgerAPI, filters: dict[str, Any]) -> dict[str, Any]:
    """The filtered record stream, plus the exact `capsule log` invocation
    that reproduces this same filtered view -- the CLI-echo standing rule
    applied to the console's own record stream/filters panel."""
    query = ScanQuery(
        agent=filters.get("agent"),
        since=filters.get("since"),
        until=filters.get("until"),
        counterparty=filters.get("counterparty"),
        verdict=filters.get("verdict"),
        action_type=filters.get("action_type"),
        limit=filters.get("limit"),
    )
    total = sum(1 for _ in store.scan(ScanQuery()))
    records = [record_summary(r) for r in store.scan(query)]
    gaps = store.find_gaps()
    return {
        "records": records,
        "total": total,
        "shown": len(records),
        "gap_count": len(gaps),
        "cli_echo": build_echo("log", flags=_echo_parts(filters)),
    }


def _fold_strip(store: LedgerAPI, developer: str) -> list[dict[str, Any]]:
    """Live fold values for this record's agent -- the catalog's own
    definitions, replayed over the real ledger. A rolling-window fold's
    anchor is the ledger's own latest record timestamp (spec §3 rule 1:
    never a wall-clock read), matching how `report/build.py` anchors its
    own replay."""
    records = [r.capsule for r in store.scan(ScanQuery())]
    if not records:
        return []
    as_of = records[-1].get("timestamp")
    catalog = Catalog(_fold_catalog_dir())
    strip: list[dict[str, Any]] = []
    for entry in catalog.list_entries():
        definition = entry.definition
        key_value = developer if definition.key else None
        try:
            trace = evaluate_one(definition, records, key_value=key_value, as_of=as_of)
        except FoldDeterminismError:
            continue
        strip.append(
            {
                "fold_id": definition.fold_id,
                "result": trace.result,
                "envelope_line": format_envelope_line(trace.to_envelope()),
            }
        )
    return strip


def record_detail(store: LedgerAPI, capsule_id: str) -> dict[str, Any] | None:
    """Everything the inspector panel needs for one selected record:
    identity fingerprint, sealed fields, verdict, which checks ran, the
    chain in both directions (what this record cites, what cites it), a
    real cryptographic verify() result, and its agent's live fold strip."""
    record = store.fetch(capsule_id)
    if record is None:
        return None

    capsule = record.capsule
    chain = capsule.get("chain") or {}
    constraints = capsule.get("constraints") or []

    parent_id = chain.get("parent_capsule_id")
    cites = None
    if parent_id:
        parent = store.fetch(parent_id)
        cites = {
            "capsule_id": parent_id,
            "fingerprint": _fingerprint(parent_id),
            "relation": chain.get("relation"),
            "found": parent is not None,
        }

    cited_by = [
        {
            "capsule_id": other.capsule_id,
            "fingerprint": _fingerprint(other.capsule_id),
            "relation": (other.capsule.get("chain") or {}).get("relation"),
        }
        for other in store.scan(ScanQuery())
        if (other.capsule.get("chain") or {}).get("parent_capsule_id") == record.capsule_id
    ]

    verify_result = store.verify(record.capsule_id)

    return {
        "capsule_id": record.capsule_id,
        "fingerprint": _fingerprint(record.capsule_id),
        "seq": record.seq,
        "sealed": capsule,
        "disposition": capsule.get("disposition") or {},
        "checks": [
            {
                "id": c.get("id"),
                "result": c.get("result"),
                "severity": c.get("severity"),
                "check_type": c.get("check_type"),
                "method": c.get("method"),
            }
            for c in constraints
        ],
        "chain": {"cites": cites, "cited_by": cited_by},
        "verify": {
            "ok": verify_result.ok if verify_result is not None else None,
            "findings": (
                [{"code": f.code, "detail": f.detail, "severity": f.severity} for f in verify_result.findings]
                if verify_result is not None
                else []
            ),
        },
        "fold_strip": _fold_strip(store, capsule.get("developer", "")),
        "cli_echo": build_echo("show", positional=record.capsule_id),
    }
