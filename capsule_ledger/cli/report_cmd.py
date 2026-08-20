# SPDX-License-Identifier: Apache-2.0
"""`capsule report`: design §3.6, the buyer's front door. Not `guard
dry-run` (design §3.5's replay-before-merge report, a different verb for a
different audience) -- this is the period, audience-scoped, three-block
record a GRC member opens monthly and an auditor opens annually.

    capsule report --pack <dir> --ledger <path> --period <since>/<until> \\
        --audience {internal,counterparty,auditor} [--out report.txt]

Hand-running this against your own ledger is the OSS engine, free forever
(build plan Phase 4 item 4, ``docs/oss-project-scope.md``'s operator-
independence test): this command is the whole verify-it-yourself surface,
not a stripped preview of a fuller operated one. **v1 only**: the "can I
check it" block lists every cited row for a human (or a script) to
spot-check by hand; the canonical-id-seeded sampler (v2) is deliberately
not built here -- it sits behind G-IP2 (build plan gate table).
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from ..audit_report import build_period_report, render_text, seal_period_report_capsule
from ..audit_report.bundle import build_report_bundle, write_report_bundle
from ..audit_report.model import AUDIENCES
from ..envcompat import env_get
from ..guards.signing import LocalSigner
from ..packs.loader import load_pack_dir
from .init_cmds import _KEY_ID_ENV, _SECRET_ENV
from .ledger_io import open_ledger, require_ledger_path

__all__ = ["add_parser", "run"]


def _parse_period(period: str | None) -> tuple[str | None, str | None]:
    """``<since>/<until>``, either side omittable (``/2026-08-01`` means "no
    lower bound"; ``2026-07-01/`` means "still open"). Absent ``--period``
    entirely means unbounded both ways."""
    if not period:
        return None, None
    if "/" not in period:
        raise ValueError(f"--period must be '<since>/<until>' (either side may be empty); got {period!r}")
    since_s, until_s = period.split("/", 1)
    return (since_s or None, until_s or None)


def add_parser(sub: argparse._SubParsersAction) -> argparse.ArgumentParser:
    p = sub.add_parser(
        "report",
        help="the three-block, audience-scoped period report (design §3.6) -- what was promised, "
        "what happened, can I check it",
    )
    p.add_argument("--pack", required=True, help="path to a pack directory (pack.yaml + referenced files)")
    p.add_argument("--ledger", help="ledger store directory or a JSONL fixture file (default: $CAPSULE_LEDGER)")
    p.add_argument("--period", default=None, help="'<since>/<until>' ISO-8601 bounds, either side optional (default: unbounded)")
    p.add_argument("--audience", required=True, choices=sorted(AUDIENCES), help="who this report is for")
    p.add_argument("--out", default="report.txt", help="output path for the rendered text report (default: %(default)s)")
    p.add_argument(
        "--bundle-out",
        dest="bundle_out",
        default=None,
        help="output path for the offline-verifiable bundle (default: derived from --out)",
    )
    p.add_argument("--operator", default="local", help="operator identity for the report's own sealed record (default: 'local')")
    p.add_argument("--developer", default="capsule-report-tool", help="developer identity for the report's own sealed record")
    p.add_argument("--key-id", default=None, help=f"signing key id (default: ${_KEY_ID_ENV})")
    p.add_argument("--secret", default=None, help=f"signing key secret (default: ${_SECRET_ENV})")
    p.set_defaults(func=run)
    return p


def _default_bundle_out(out: str) -> str:
    p = Path(out)
    candidate = p.with_suffix(".bundle.json")
    if str(candidate) == out:
        candidate = p.with_name(p.stem + "-bundle.json")
    return str(candidate)


def run(args: argparse.Namespace) -> int:
    from ..telemetry.record import record_evidence_touch

    record_evidence_touch("full")

    ledger_path = require_ledger_path("report", args)
    if ledger_path is None:
        return 2

    try:
        since, until = _parse_period(args.period)
    except ValueError as exc:
        print(f"capsule report: {exc}", file=sys.stderr)
        return 2

    try:
        pack = load_pack_dir(args.pack)
    except Exception as exc:  # noqa: BLE001 -- surfaced verbatim to the operator, same as other pack-loading CLI verbs
        print(f"capsule report: could not load pack at {args.pack!r}: {exc}", file=sys.stderr)
        return 2

    key_id = args.key_id or env_get(_KEY_ID_ENV)
    secret_text = args.secret or env_get(_SECRET_ENV)
    if not key_id or not secret_text:
        print(f"capsule report: --key-id/--secret are required (or set ${_KEY_ID_ENV}/${_SECRET_ENV})", file=sys.stderr)
        return 2
    signer = LocalSigner(key_id=key_id, secret=secret_text.encode("utf-8"))

    generated_at = datetime.now(timezone.utc).isoformat()

    with open_ledger(ledger_path) as store:
        report = build_period_report(
            store, pack, audience=args.audience, since=since, until=until, generated_at=generated_at
        )
        report_capsule = seal_period_report_capsule(
            report, operator=args.operator, developer=args.developer, signer=signer, timestamp=generated_at
        )
        bundle = build_report_bundle(store, report_capsule=report_capsule, cited_capsule_ids=report.cited_capsule_ids)

    bundle_out = args.bundle_out or _default_bundle_out(args.out)
    write_report_bundle(bundle, bundle_out)

    report = report.with_seal(report_capsule_id=report_capsule["capsule_id"], bundle_path=bundle_out)
    text = render_text(report)
    Path(args.out).write_text(text, encoding="utf-8")

    print(f"wrote {args.out}")
    print(f"wrote {bundle_out} ({len(bundle['records'])} record(s), {'all check out' if bundle['all_ok'] else 'CHECK FAILED in this bundle'})")
    print(f"report record: {report_capsule['capsule_id']}")
    return 0 if bundle["all_ok"] else 1
