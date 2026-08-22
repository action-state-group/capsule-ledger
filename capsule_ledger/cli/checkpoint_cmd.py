# SPDX-License-Identifier: Apache-2.0
"""`capsule checkpoint` verbs: emit, status, verify.

  emit   — produce a signed checkpoint of the current MMR peak set, register its
           digest with a Transparency Service (optional), and store the receipt.
  status — show the last checkpoint and how many entries have been appended
           since then ("witnessed up to size S at time T, N entries behind").
  verify — end-to-end integrity: inclusion-to-peak + checkpoint signature +
           receipt offline verification + rollback detection.

External checkpointing requires scitt-cose (``pip install
'capsule-ledger[checkpoint]'``). Checkpoint *emit* works without it (operator
can skip the TS step with ``--no-register``); ``verify`` always needs it.
"""
from __future__ import annotations

import argparse
import sys

__all__ = ["add_parser"]

_KEY_ID_ENV = "CAPSULE_MCP_SIGNING_KEY_ID"
_KEY_ID_ENV_LEGACY = "ASG_MCP_SIGNING_KEY_ID"
_SECRET_ENV = "CAPSULE_MCP_SIGNING_SECRET"
_SECRET_ENV_LEGACY = "ASG_MCP_SIGNING_SECRET"


def _utc_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _build_signer(args: argparse.Namespace):
    from ..envcompat import env_get
    from ..guards.signing import LocalSigner

    key_id = getattr(args, "key_id", None) or env_get(_KEY_ID_ENV, _KEY_ID_ENV_LEGACY)
    secret_text = getattr(args, "key_secret", None) or env_get(_SECRET_ENV, _SECRET_ENV_LEGACY)
    if not key_id or not secret_text:
        print(
            f"capsule checkpoint: signing key required "
            f"(--key-id/--key-secret or ${_KEY_ID_ENV}/${_SECRET_ENV})",
            file=sys.stderr,
        )
        return None
    return LocalSigner(key_id=key_id, secret=secret_text.encode("utf-8"))


def _open_mmr_ledger(ledger_path: str):
    from ..ledger.store import LedgerStore
    from ..mmr.index import MmrLedger

    store = LedgerStore(ledger_path)
    mmr = MmrLedger(store)
    mmr.sync()
    return store, mmr


def _cmd_emit(args: argparse.Namespace) -> int:
    from ..mmr.checkpoint import (
        DEFAULT_TS_URL,
        CheckpointError,
        RollbackError,
        emit_checkpoint,
        load_config,
        load_latest_checkpoint,
        register_checkpoint,
        save_checkpoint,
    )
    from .ledger_io import require_ledger_path

    ledger_path = require_ledger_path("checkpoint emit", args)
    if ledger_path is None:
        return 2

    signer = _build_signer(args)
    if signer is None:
        return 2

    store, mmr = _open_mmr_ledger(ledger_path)
    ledger_root = store.root

    try:
        prev = load_latest_checkpoint(ledger_root)

        try:
            cp = emit_checkpoint(mmr, signer, prev=prev)
        except RollbackError as exc:
            print(f"✗ rollback detected: {exc}", file=sys.stderr)
            return 1
        except CheckpointError as exc:
            print(f"✗ checkpoint error: {exc}", file=sys.stderr)
            return 1

        # Register with each TS unless skipped.
        ts_urls = args.ts_url or []
        if not ts_urls and not args.no_register:
            cfg = load_config(ledger_root)
            ts_urls = cfg.ts_urls if cfg else [DEFAULT_TS_URL]

        for ts_url in ts_urls:
            if args.no_register:
                break
            print(f"  registering with {ts_url} …", end="", flush=True)
            try:
                witness = register_checkpoint(cp, ts_url, timeout=args.timeout)
                cp.witnesses.append(witness)
                print(f" leaf_index={witness.leaf_index} tree_size={witness.tree_size} ✓")
            except CheckpointError as exc:
                print(f" FAILED: {exc}", file=sys.stderr)
                if args.require_ts:
                    return 1

        p = save_checkpoint(ledger_root, cp)
        print(f"checkpoint: mmr_size={cp.mmr_size} at {cp.timestamp}")
        print(f"  root={cp.root}")
        print(f"  key_id={cp.key_id}")
        print(f"  digest={cp.digest()}")
        print(f"  saved → {p}")
        if cp.witnesses:
            print(f"  witnesses: {len(cp.witnesses)}")
        return 0
    finally:
        store.close()


def _cmd_status(args: argparse.Namespace) -> int:
    from ..mmr.checkpoint import (
        list_checkpoints,
        load_config,
        load_latest_checkpoint,
    )
    from ..mmr.core import leaf_count
    from .ledger_io import require_ledger_path

    ledger_path = require_ledger_path("checkpoint status", args)
    if ledger_path is None:
        return 2

    store, mmr = _open_mmr_ledger(ledger_path)
    ledger_root = store.root
    store.close()

    cp = load_latest_checkpoint(ledger_root)
    current_entries = mmr.leaf_count()

    if cp is None:
        print(f"no checkpoints yet; {current_entries} entries in log")
        cfg = load_config(ledger_root)
        if cfg is None:
            print("  (checkpointing not configured; run: capsule checkpoint emit)")
        else:
            print(f"  cadence={cfg.cadence_entries} max_lag={cfg.max_lag_entries}")
        return 0

    witnessed_entries = leaf_count(cp.mmr_size)
    lag = current_entries - witnessed_entries

    print(f"witnessed up to size {cp.mmr_size} at {cp.timestamp}")
    print(f"  witnessed_entries={witnessed_entries}  current_entries={current_entries}  lag={lag}")
    print(f"  root={cp.root}")
    print(f"  key_id={cp.key_id}")
    print(f"  witnesses: {len(cp.witnesses)}")
    for w in cp.witnesses:
        print(f"    {w.ts_url}  leaf_index={w.leaf_index}  tree_size={w.tree_size}")

    cfg = load_config(ledger_root)
    if cfg and lag > cfg.max_lag_entries:
        print(f"  ⚠ lag {lag} exceeds max_lag_entries={cfg.max_lag_entries}; emit a new checkpoint")

    all_sizes = list_checkpoints(ledger_root)
    print(f"  total checkpoints: {len(all_sizes)}")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    from ..mmr import core
    from ..mmr.checkpoint import (
        CheckpointRecord,
        list_checkpoints,
        load_checkpoint,
        load_ts_pubkey,
        verify_checkpoint_consistency,
        verify_checkpoint_signature,
        verify_receipt_offline,
    )
    from .ledger_io import require_ledger_path

    ledger_path = require_ledger_path("checkpoint verify", args)
    if ledger_path is None:
        return 2

    store, mmr = _open_mmr_ledger(ledger_path)
    ledger_root = store.root
    store.close()

    signer = _build_signer(args)
    if signer is None:
        return 2

    all_sizes = list_checkpoints(ledger_root)
    if not all_sizes:
        print("no checkpoints to verify")
        return 2

    all_ok = True

    prev: CheckpointRecord | None = None
    for size in all_sizes:
        cp = load_checkpoint(ledger_root, size)
        if cp is None:
            continue
        label = f"checkpoint mmr_size={size}"

        # 1. Signature check.
        if verify_checkpoint_signature(cp, signer):
            print(f"  ✓ {label}: signature ok")
        else:
            print(f"  ✗ {label}: signature INVALID")
            all_ok = False

        # 2. Rollback detection (not the first checkpoint).
        if prev is not None:
            if verify_checkpoint_consistency(prev, cp, mmr):
                print(f"  ✓ {label}: consistent with prev (size={prev.mmr_size})")
            else:
                print(f"  ✗ {label}: INCONSISTENT with prev (size={prev.mmr_size}) — possible rollback")
                all_ok = False

        # 3. Inclusion-to-peak: verify the latest leaf is genuinely in the MMR.
        if size <= mmr.size():
            witnessed_leaf_count = core.leaf_count(size)
            last_seq = witnessed_leaf_count
            if last_seq >= 1 and last_seq <= mmr.leaf_count():
                try:
                    proof = mmr.inclusion_proof(last_seq, size=size)
                    body_digest = mmr.body_digest(last_seq)
                    root = bytes.fromhex(cp.root)
                    ok = core.verify_inclusion(root, size, last_seq - 1, body_digest, proof)
                    mark = "✓" if ok else "✗"
                    state = "ok" if ok else "FAILED"
                    print(f"  {mark} {label}: inclusion proof for seq={last_seq} {state}")
                    if not ok:
                        all_ok = False
                except Exception as exc:
                    print(f"  ✗ {label}: inclusion proof error: {exc}")
                    all_ok = False

        # 4. Receipt verification for each witness.
        for w in cp.witnesses:
            pubkey_pem = load_ts_pubkey(ledger_root, w.ts_url)
            ok, errors = verify_receipt_offline(
                w,
                ts_pubkey_pem=pubkey_pem,
                ts_base_url=w.ts_url if pubkey_pem is None else None,
            )
            if ok:
                print(f"  ✓ {label}: receipt verified (witness={w.ts_url}, leaf_index={w.leaf_index})")
            else:
                print(f"  ✗ {label}: receipt FAILED (witness={w.ts_url}): {errors}")
                all_ok = False

        prev = cp

    # Cadence lag check on the latest.
    if prev is not None:
        from ..mmr.checkpoint import load_config
        from ..mmr.core import leaf_count as lc

        current_entries = mmr.leaf_count()
        witnessed_entries = lc(prev.mmr_size)
        lag = current_entries - witnessed_entries
        print(f"\nwitnessed up to size {prev.mmr_size} at {prev.timestamp}")
        print(f"lag: {lag} entries (current={current_entries}, witnessed={witnessed_entries})")

        cfg = load_config(ledger_root)
        if cfg and lag > cfg.max_lag_entries:
            print(f"  ⚠ lag exceeds max_lag_entries={cfg.max_lag_entries}")

    print()
    if all_ok:
        print("✓ all checkpoints verify clean")
    else:
        print("✗ verification FAILED")
    return 0 if all_ok else 1


def _cmd_init(args: argparse.Namespace) -> int:
    from ..mmr.checkpoint import DEFAULT_TS_URL, CheckpointConfig, save_config
    from .ledger_io import require_ledger_path

    ledger_path = require_ledger_path("checkpoint init", args)
    if ledger_path is None:
        return 2

    from ..ledger.store import LedgerStore
    store = LedgerStore(ledger_path)
    ledger_root = store.root
    store.close()

    ts_urls = args.ts_url or [DEFAULT_TS_URL]
    cfg = CheckpointConfig(
        ts_urls=ts_urls,
        cadence_entries=args.cadence,
        max_lag_entries=args.max_lag,
    )
    save_config(ledger_root, cfg)
    print(f"checkpoint config written to {ledger_root}/checkpoints/config.json")
    print(f"  ts_urls: {cfg.ts_urls}")
    print(f"  cadence_entries: {cfg.cadence_entries}")
    print(f"  max_lag_entries: {cfg.max_lag_entries}")
    return 0


def add_parser(sub: argparse._SubParsersAction) -> argparse.ArgumentParser:
    cp = sub.add_parser("checkpoint", help="MMR peaks checkpointing: emit, status, verify")
    cp_sub = cp.add_subparsers(dest="checkpoint_command")
    cp.set_defaults(cp_parser=cp)

    # -- init ----------------------------------------------------------------
    p_init = cp_sub.add_parser("init", help="write checkpoint config (cadence, TS URLs)")
    p_init.add_argument("--ledger", help="ledger store directory (default: $CAPSULE_LEDGER)")
    p_init.add_argument("--ts-url", action="append", metavar="URL",
                        help="Transparency Service URL (repeatable; default: capsule-anchor public)")
    p_init.add_argument("--cadence", type=int, default=100,
                        help="emit a checkpoint every N entries (default: 100)")
    p_init.add_argument("--max-lag", type=int, default=200,
                        help="warn if unwitnessed entries exceed N (default: 200)")
    p_init.set_defaults(func=_cmd_init)

    # -- emit ----------------------------------------------------------------
    p_emit = cp_sub.add_parser("emit", help="emit a signed checkpoint and register with TS")
    p_emit.add_argument("--ledger", help="ledger store directory (default: $CAPSULE_LEDGER)")
    p_emit.add_argument("--key-id", help=f"signing key ID (default: ${_KEY_ID_ENV})")
    p_emit.add_argument("--key-secret", help=f"signing key secret (default: ${_SECRET_ENV})")
    p_emit.add_argument("--ts-url", action="append", metavar="URL",
                        help="Transparency Service URL (repeatable; overrides config)")
    p_emit.add_argument("--no-register", action="store_true",
                        help="sign the checkpoint but do NOT register with any TS")
    p_emit.add_argument("--require-ts", action="store_true",
                        help="exit 1 if any TS registration fails (default: warn only)")
    p_emit.add_argument("--timeout", type=float, default=30.0,
                        help="HTTP timeout in seconds for TS registration (default: 30)")
    p_emit.set_defaults(func=_cmd_emit)

    # -- status --------------------------------------------------------------
    p_status = cp_sub.add_parser(
        "status", help="show last checkpoint and unwitnessed entry count"
    )
    p_status.add_argument("--ledger", help="ledger store directory (default: $CAPSULE_LEDGER)")
    p_status.set_defaults(func=_cmd_status)

    # -- verify --------------------------------------------------------------
    p_verify = cp_sub.add_parser(
        "verify",
        help="end-to-end: inclusion + signature + receipt + rollback detection",
    )
    p_verify.add_argument("--ledger", help="ledger store directory (default: $CAPSULE_LEDGER)")
    p_verify.add_argument("--key-id", help=f"signing key ID (default: ${_KEY_ID_ENV})")
    p_verify.add_argument("--key-secret", help=f"signing key secret (default: ${_SECRET_ENV})")
    p_verify.set_defaults(func=_cmd_verify)

    return cp
