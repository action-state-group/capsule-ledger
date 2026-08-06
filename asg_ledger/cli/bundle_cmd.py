# SPDX-License-Identifier: Apache-2.0
"""`capsule bundle`: a self-contained, independently verifiable slice of the
ledger, plus a verify-surface permalink.

"Self-contained" is load-bearing: the bundle transitively pulls in any
``chain.parent_capsule_id`` a selected record cites (walking the real
ledger) so the slice verifies on its own, without needing the rest of the
ledger present -- verification below runs with ``store=`` restricted to
exactly the bundle's own capsule ids, never the full ledger, to prove that
property rather than assume it.

The permalink is fragment-carried (``#...``, after the URL's ``#``): per
the workspace's other verify surfaces (`agentactioncapsule-site` /
`scitt-cose`'s hosted verifier), capsule data that goes after ``#`` is never
sent to a server -- only the browser-side JS reads it. ``verify.
agentactioncapsule.org`` is this workspace's existing public verify domain
(see CLAUDE.md / STATUS.md T7 notes); the base URL is still overridable
(``--verify-base-url`` / ``$ASG_VERIFY_BASE_URL``) since no bundle-specific
route exists there yet -- this is this package's own convention until one
does.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
from datetime import datetime, timezone

from agent_action_capsule import verify as verify_capsule

from ..ledger.api import ScanQuery
from .format import build_echo, format_staleness
from .ledger_io import add_scan_query_args, build_scan_query, echo_parts, open_ledger, require_ledger_path

__all__ = ["add_parser", "run"]

DEFAULT_VERIFY_BASE_URL = "https://verify.agentactioncapsule.org/bundle"


def add_parser(sub: argparse._SubParsersAction) -> argparse.ArgumentParser:
    p = sub.add_parser("bundle", help="produce a self-contained verifiable slice of the ledger")
    add_scan_query_args(p)
    p.add_argument("--out", default="bundle.json", help="output path for the bundle file (default: %(default)s)")
    p.add_argument(
        "--verify-base-url",
        dest="verify_base_url",
        default=os.environ.get("ASG_VERIFY_BASE_URL", DEFAULT_VERIFY_BASE_URL),
        help="base URL the permalink's fragment is appended to (default: %(default)s)",
    )
    p.set_defaults(func=run)
    return p


def _collect_with_parents(store, matched):
    """Pull in any cited chain parent not already selected, so the bundle
    verifies standalone without needing the rest of the ledger. A parent
    that genuinely isn't in the ledger (a real gap) is left out -- it
    surfaces honestly as a finding on the citing record, never hidden."""
    by_id = {r.capsule_id: r for r in matched}
    frontier = list(matched)
    missing: set[str] = set()
    while frontier:
        rec = frontier.pop()
        parent_id = (rec.capsule.get("chain") or {}).get("parent_capsule_id")
        if not parent_id or parent_id in by_id or parent_id in missing:
            continue
        parent = store.fetch(parent_id)
        if parent is None:
            missing.add(parent_id)
            continue
        by_id[parent.capsule_id] = parent
        frontier.append(parent)
    return sorted(by_id.values(), key=lambda r: r.seq)


def run(args: argparse.Namespace) -> int:
    # ``bundle`` only exists at all in the "full" packaging arm -- see
    # ``cli/main.py`` -- so any use of it is M5's "bundle/share created" fact.
    from ..telemetry.record import record_evidence_touch

    record_evidence_touch("full")

    ledger_path = require_ledger_path("bundle", args)
    if ledger_path is None:
        return 2

    query = build_scan_query(args)
    with open_ledger(ledger_path) as store:
        matched = list(store.scan(query))
        records = _collect_with_parents(store, matched)
        capsules = [r.capsule for r in records]
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

        tree_size = sum(1 for _ in store.scan(ScanQuery()))

    echo = build_echo("bundle", flags=[*echo_parts(args), ("--out", args.out)])
    bundle = {
        "bundle_version": "1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "query": {
            k: v
            for k, v in {
                "agent": args.agent,
                "since": args.since,
                "until": args.until,
                "counterparty": args.counterparty,
                "verdict": args.verdict,
                "action_type": args.action_type,
                "limit": args.limit,
            }.items()
            if v is not None
        },
        "cli_echo": echo,
        "records": capsules,
        "range": [records[0].seq, records[-1].seq] if records else [0, -1],
        "checkpoint": {"tree_size": tree_size},
        "verification": verification,
    }

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(bundle, fh, indent=2, sort_keys=True)

    payload = json.dumps(bundle, separators=(",", ":"), sort_keys=True).encode("utf-8")
    fragment = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    permalink = f"{args.verify_base_url}#{fragment}"

    r0, r1 = bundle["range"]
    status = "all verify" if all_ok else "VERIFICATION FAILURE in this slice"
    print(f"wrote {args.out} ({len(records)} record(s), records {r0}–{r1}, {status})")
    print(f"checkpoint #{tree_size} · as of {format_staleness(0)}")
    print(f"verify: {permalink}")
    print()
    print(echo)
    return 0 if all_ok else 1
