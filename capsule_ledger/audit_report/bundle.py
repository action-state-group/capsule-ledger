# SPDX-License-Identifier: Apache-2.0
"""The report's own offline-verifiable artifact -- design §3.6 item 3's "can
I check it" block needs something an auditor can run `capsule verify
--bundle` against with no network and no permission from us. Same
transitively-pull-chain-parents shape ``cli/bundle_cmd.py``'s
``capsule bundle`` already uses, applied here to exactly the capsules a
report cites (plus the report's own seal capsule) -- never the whole
ledger, and never anything beyond what the rendered rows already named.
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime, timezone

from agent_action_capsule import verify as verify_capsule

__all__ = ["build_report_bundle", "write_report_bundle"]


def _collect_with_parents(store, capsule_ids: Iterable[str]) -> dict[str, dict]:
    by_id: dict[str, dict] = {}
    frontier = []
    for cid in capsule_ids:
        record = store.fetch(cid)
        if record is None:
            continue
        by_id[cid] = record.capsule
        frontier.append(record)

    stack = list(frontier)
    while stack:
        rec = stack.pop()
        parent_id = (rec.capsule.get("chain") or {}).get("parent_capsule_id")
        if not parent_id or parent_id in by_id:
            continue
        parent = store.fetch(parent_id)
        if parent is None:
            continue
        by_id[parent_id] = parent.capsule
        stack.append(parent)
    return by_id


def build_report_bundle(store, *, report_capsule: dict, cited_capsule_ids: Iterable[str]) -> dict:
    """Build the bundle dict (same ``{"records": [...]}`` shape
    ``cli/verify_cmd.py``'s ``capsule verify --bundle`` already reads).
    ``report_capsule`` is included directly rather than fetched -- it may
    not have been appended to ``store`` yet at call time."""
    by_id = _collect_with_parents(store, cited_capsule_ids)
    by_id[report_capsule["capsule_id"]] = report_capsule
    capsules = list(by_id.values())
    ids = [c["capsule_id"] for c in capsules]

    verification: dict[str, dict] = {}
    all_ok = True
    for capsule in capsules:
        result = verify_capsule(capsule, store=ids)
        verification[capsule["capsule_id"]] = {
            "ok": result.ok,
            "findings": [{"code": f.code, "detail": f.detail, "severity": f.severity} for f in result.findings],
        }
        all_ok = all_ok and result.ok

    return {
        "bundle_version": "1",
        "bundle_kind": "capsule_report",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "records": capsules,
        "verification": verification,
        "all_ok": all_ok,
    }


def write_report_bundle(bundle: dict, out_path: str) -> None:
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(bundle, fh, indent=2, sort_keys=True)
