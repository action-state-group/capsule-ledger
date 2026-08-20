# SPDX-License-Identifier: Apache-2.0
"""``capsule confirm ingest``: drive the confirm-ingester (``capsule_ledger.confirm``)
from the CLI against the built-in mock IdP connector, for demos and manual
testing of the connector interface without writing a script.

``--status``/``--external-ref``/``--observed-at``/``--evidence-json`` are
what a live connector's own read would return; here they seed
``MockIdPConnector`` for exactly one read, so this command exercises the
real ``ConfirmIngestEngine.ingest`` path a real connector integration also
goes through (``docs/confirm-connector-interface.md``). Omitting ``--status``
models "the third system hasn't settled this yet" -- the engine reports
``pending`` and appends nothing, same as a real connector with nothing new
to report.
"""
from __future__ import annotations

import argparse
import json
import sys

from ..confirm import ConfirmIngestEngine, ConfirmStatus
from ..confirm.connectors import MockIdPConnector
from ..envcompat import env_get
from ..guards.signing import LocalSigner
from .init_cmds import _KEY_ID_ENV, _SECRET_ENV
from .ledger_io import open_ledger, require_ledger_path

__all__ = ["add_parser"]

_KNOWN_CONNECTORS = ("mock-idp",)


def _parse_evidence_json(raw: str | None) -> tuple[dict | None, str | None]:
    """Parse ``--evidence-json``, returning ``(value, error)`` instead of
    letting a malformed payload raise ``json.JSONDecodeError`` straight
    through ``main()`` as a Python traceback (Finding G,
    delta-adversarial-report SCOPE 2). No capsule is built either way --
    the crash always happened before the engine was called -- this only
    changes whether the caller sees a clean, actionable message or a
    traceback.
    """
    if not raw:
        return None, None
    try:
        return json.loads(raw), None
    except json.JSONDecodeError as exc:
        return None, f"--evidence-json is not valid JSON: {exc}"


def _build_mock_connector(args: argparse.Namespace, evidence: dict | None) -> MockIdPConnector:
    connector = MockIdPConnector()
    if args.status is not None:
        connector.set_state(
            subject=args.subject,
            predicate=args.predicate,
            status=args.status,
            external_ref=args.external_ref,
            observed_at=args.observed_at,
            evidence=evidence,
        )
    return connector


def _cmd_confirm_ingest(args: argparse.Namespace) -> int:
    ledger_path = require_ledger_path("confirm ingest", args)
    if ledger_path is None:
        return 2

    if args.connector not in _KNOWN_CONNECTORS:
        print(
            f"capsule confirm ingest: unknown connector {args.connector!r} "
            f"(built in: {', '.join(_KNOWN_CONNECTORS)}; see docs/confirm-connector-interface.md "
            "to wire a real one)",
            file=sys.stderr,
        )
        return 2
    if args.status is not None and not args.external_ref:
        print("capsule confirm ingest: --external-ref is required together with --status", file=sys.stderr)
        return 2
    if args.status is not None and not args.observed_at:
        print("capsule confirm ingest: --observed-at is required together with --status", file=sys.stderr)
        return 2

    evidence, evidence_error = _parse_evidence_json(args.evidence_json)
    if evidence_error is not None:
        print(f"capsule confirm ingest: {evidence_error}", file=sys.stderr)
        return 2

    key_id = args.key_id or env_get(_KEY_ID_ENV)
    secret_text = args.secret or env_get(_SECRET_ENV)
    if not key_id or not secret_text:
        print(
            f"capsule confirm ingest: --key-id/--secret are required (or set ${_KEY_ID_ENV}/${_SECRET_ENV})",
            file=sys.stderr,
        )
        return 2
    signer = LocalSigner(key_id=key_id, secret=secret_text.encode("utf-8"))

    connector = _build_mock_connector(args, evidence)

    with open_ledger(ledger_path) as store:
        engine = ConfirmIngestEngine(ledger=store, connector=connector, signer_provider=lambda: signer)
        decision = engine.ingest(args.commitment, subject=args.subject, predicate=args.predicate)

    if decision.status == ConfirmStatus.PENDING:
        print(f"pending: {decision.reason}")
        return 0
    if decision.status == ConfirmStatus.ERROR:
        print(f"capsule confirm ingest: {decision.reason}", file=sys.stderr)
        return 1

    label = "already recorded" if decision.status == ConfirmStatus.ALREADY_RECORDED else "recorded"
    print(f"{label}: {decision.effect_status} — {decision.capsule['capsule_id']}")
    print(f"  chained to {args.commitment} (relation=confirms)")
    return 0


def add_parser(sub: argparse._SubParsersAction) -> argparse.ArgumentParser:
    confirm = sub.add_parser("confirm", help="external-system confirmation ingestion (fulfillment capsules)")
    confirm_sub = confirm.add_subparsers(dest="confirm_command")
    confirm.set_defaults(confirm_parser=confirm)

    p_ingest = confirm_sub.add_parser(
        "ingest", help="read one connector observation and, if settled, seal a fulfillment capsule"
    )
    p_ingest.add_argument("--ledger", help="ledger store directory or a JSONL fixture file (default: $CAPSULE_LEDGER)")
    p_ingest.add_argument("--commitment", required=True, help="capsule_id of the commitment this confirmation chains to")
    p_ingest.add_argument("--subject", required=True, help="the (subject, predicate) pair the connector reads, e.g. a user id")
    p_ingest.add_argument("--predicate", required=True, help="the (subject, predicate) pair the connector reads, e.g. mfa_enabled")
    p_ingest.add_argument("--connector", default="mock-idp", help="connector type (default: mock-idp, the only one built in)")
    p_ingest.add_argument(
        "--status", choices=("confirmed", "failed"), default=None,
        help="the connector's own read for this call (omit to model 'nothing observed yet' -- reports pending)",
    )
    p_ingest.add_argument("--external-ref", default=None, help="the third system's own reference for this event (required with --status)")
    p_ingest.add_argument("--observed-at", default=None, help="ISO-8601 timestamp the third system reports (required with --status)")
    p_ingest.add_argument("--evidence-json", default=None, help="JSON object: the connector's raw evidence (default: a minimal synthesized one)")
    p_ingest.add_argument("--key-id", default=None, help=f"signing key id (default: ${_KEY_ID_ENV})")
    p_ingest.add_argument("--secret", default=None, help=f"signing key secret (default: ${_SECRET_ENV})")
    p_ingest.set_defaults(func=_cmd_confirm_ingest)

    return confirm
