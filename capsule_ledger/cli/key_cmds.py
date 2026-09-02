# SPDX-License-Identifier: Apache-2.0
"""``capsule key`` verbs: rotate the signing key and record the rotation as a
real, verifiable ledger event; show the key timeline the ledger implies.

``rotate`` reuses ``build_event_capsule`` + ``LedgerAPI.append`` -- the exact
mechanism every other write path in this package uses -- so the rotation
event is a real capsule, not a side channel. It is signed by the *outgoing*
key: that is the last legitimate act of the key being retired, so a rotation
record can't be forged by someone who only holds the incoming key. See
``cll.revocation`` for how a verifier later reconstructs the key timeline
this event feeds and enforces time-fenced revocation from it -- ``cll``
now carries this check (ported from this repo's own former
``ledger/revocation.py``, #126 fix, 2026-09-02).
"""
from __future__ import annotations

import argparse
import secrets
import sys
from datetime import datetime, timezone

from cll.revocation import ROTATION_EVENT, build_key_timeline

from ..envcompat import env_get
from ..ledger.capsule import build_event_capsule
from ..ledger.signing import LocalSigner, key_fingerprint
from .ledger_io import open_ledger, require_ledger_path

__all__ = ["add_parser"]

_KEY_ID_ENV = "CAPSULE_MCP_SIGNING_KEY_ID"
_SECRET_ENV = "CAPSULE_MCP_SIGNING_SECRET"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _cmd_key_rotate(args: argparse.Namespace) -> int:
    ledger_path = require_ledger_path("key rotate", args)
    if ledger_path is None:
        return 2

    old_key_id = args.old_key_id or env_get(_KEY_ID_ENV)
    old_secret_text = args.old_secret or env_get(_SECRET_ENV)
    if not old_key_id or not old_secret_text:
        print(
            f"capsule key rotate: --old-key-id/--old-secret are required (or set ${_KEY_ID_ENV}/${_SECRET_ENV})",
            file=sys.stderr,
        )
        return 2
    if not args.new_key_id:
        print("capsule key rotate: --new-key-id is required", file=sys.stderr)
        return 2
    if args.new_key_id == old_key_id:
        print("capsule key rotate: --new-key-id must differ from the outgoing key id", file=sys.stderr)
        return 2

    old_secret = old_secret_text.encode("utf-8")
    generated_secret = args.new_secret is None
    new_secret_text = args.new_secret or secrets.token_hex(32)
    new_secret = new_secret_text.encode("utf-8")

    old_signer = LocalSigner(key_id=old_key_id, secret=old_secret)

    rotated_at = args.at or _utc_now()

    with open_ledger(ledger_path) as store:
        detail = {
            "old_key_id": old_key_id,
            "old_key_fingerprint": key_fingerprint(old_key_id, old_secret),
            "new_key_id": args.new_key_id,
            "new_key_fingerprint": key_fingerprint(args.new_key_id, new_secret),
            "rotated_at": rotated_at,
        }
        if args.reason:
            detail["reason"] = args.reason

        capsule = build_event_capsule(
            operator=args.operator,
            developer=args.developer,
            signer=old_signer,
            event=ROTATION_EVENT,
            detail=detail,
            timestamp=rotated_at,
        )
        record = store.append(capsule, consequential=True)

    print(f"rotated: {old_key_id} -> {args.new_key_id} at {rotated_at}")
    print(f"recorded as {record.capsule_id}")
    print(f"  old_key_fingerprint: {detail['old_key_fingerprint']}")
    print(f"  new_key_fingerprint: {detail['new_key_fingerprint']}")
    if generated_secret:
        print()
        print("new signing secret (shown once -- this command does not persist it anywhere):")
        print(f"  {new_secret_text}")
        print(f"export {_KEY_ID_ENV}={args.new_key_id}")
        print(f"export {_SECRET_ENV}={new_secret_text}")
    return 0


def _cmd_key_status(args: argparse.Namespace) -> int:
    ledger_path = require_ledger_path("key status", args)
    if ledger_path is None:
        return 2

    with open_ledger(ledger_path) as store:
        timeline = build_key_timeline(store)

    if not timeline:
        print("no key_rotation events recorded in this ledger yet")
        current = env_get(_KEY_ID_ENV)
        if current:
            print(f"$({_KEY_ID_ENV}) = {current!r} (no rotation history for it)")
        return 0

    for key_id, window in sorted(timeline.items(), key=lambda kv: kv[1].activated_at or ""):
        state = "live" if window.revoked_at is None else f"revoked at {window.revoked_at}"
        activated = window.activated_at or "(unrecorded)"
        print(f"{key_id}\tactivated {activated}\t{state}")
    return 0


def add_parser(sub: argparse._SubParsersAction) -> argparse.ArgumentParser:
    key = sub.add_parser("key", help="signing-key lifecycle: rotate + status, recorded in the ledger")
    key_sub = key.add_subparsers(dest="key_command")
    key.set_defaults(key_parser=key)

    p_rotate = key_sub.add_parser(
        "rotate", help="rotate the active signing key and record a key_rotation event in the ledger"
    )
    p_rotate.add_argument("--ledger", help="ledger store directory or a JSONL fixture file (default: $CAPSULE_LEDGER)")
    p_rotate.add_argument(
        "--old-key-id", help=f"outgoing key id (default: ${_KEY_ID_ENV})"
    )
    p_rotate.add_argument(
        "--old-secret", help=f"outgoing key secret, used only to sign this rotation event (default: ${_SECRET_ENV})"
    )
    p_rotate.add_argument("--new-key-id", required=True, help="incoming key id")
    p_rotate.add_argument(
        "--new-secret", default=None, help="incoming key secret (default: a fresh random secret, printed once)"
    )
    p_rotate.add_argument("--operator", required=True, help="who/what triggered this rotation (capsule operator)")
    p_rotate.add_argument("--developer", required=True, help="who/what triggered this rotation (capsule developer)")
    p_rotate.add_argument("--reason", default=None, help="optional free-text reason, recorded in the event detail")
    p_rotate.add_argument("--at", default=None, help="override the rotation timestamp (default: now, UTC)")
    p_rotate.set_defaults(func=_cmd_key_rotate)

    p_status = key_sub.add_parser("status", help="print the key timeline this ledger's rotation events imply")
    p_status.add_argument("--ledger", help="ledger store directory or a JSONL fixture file (default: $CAPSULE_LEDGER)")
    p_status.set_defaults(func=_cmd_key_status)

    return key
