# SPDX-License-Identifier: Apache-2.0
"""`capsule manifest` verbs: the declare-attest-verify surface for guard
policy (see ``asg_ledger.policy``'s module docstring).

  show     -- resolve a manifest against the real fold/wicket catalogs and
              print its digest (fail closed on any drift or unknown ref).
  activate -- append a signed config-change record (an "fyi" event capsule,
              ``chain.relation=epoch_opens``) citing the manifest's own
              digest, chained to the ledger's previous activation if any.
  verify   -- confirm a decision capsule's cited ``asg_payload.manifest_digest``
              actually corresponds to a real, loadable manifest.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from ..guards.signing import LocalSigner
from ..ledger import LedgerStore
from ..policy import (
    PolicyManifestError,
    build_manifest_activation_capsule,
    find_latest_activation,
    load_manifest_file,
    resolve_manifest,
)
from .ledger_io import open_ledger, require_ledger_path

__all__ = ["add_parser"]

DEFAULT_MANIFEST_PATH = Path(__file__).resolve().parent.parent / "policy" / "catalog_defs" / "default.yaml"
DEFAULT_FOLD_DIR = Path(__file__).resolve().parent.parent / "folds" / "catalog_defs"
DEFAULT_WICKET_DIR = Path(__file__).resolve().parent.parent / "guards" / "wickets" / "catalog_defs"

_DEFAULT_SIGNING_KEY_ID = "capsule-cli-manifest"
_DEFAULT_SIGNING_SECRET = b"capsule-cli-manifest-dev-key"


def _manifest_path(args: argparse.Namespace) -> Path:
    return Path(args.manifest) if args.manifest else DEFAULT_MANIFEST_PATH


def _fold_dir(args: argparse.Namespace) -> Path:
    if args.fold_dir:
        return Path(args.fold_dir)
    env = os.environ.get("ASG_FOLD_DIR")
    return Path(env) if env else DEFAULT_FOLD_DIR


def _wicket_dir(args: argparse.Namespace) -> Path:
    if args.wicket_dir:
        return Path(args.wicket_dir)
    env = os.environ.get("ASG_WICKET_DIR")
    return Path(env) if env else DEFAULT_WICKET_DIR


def _signer_from_env() -> LocalSigner:
    return LocalSigner(
        key_id=os.environ.get("ASG_LEDGER_SIGNING_KEY_ID", _DEFAULT_SIGNING_KEY_ID),
        secret=os.environ.get("ASG_LEDGER_SIGNING_SECRET", "").encode("utf-8") or _DEFAULT_SIGNING_SECRET,
    )


def _add_resolve_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--manifest", help=f"manifest YAML path (default: built-in {DEFAULT_MANIFEST_PATH.name})")
    p.add_argument("--fold-dir", dest="fold_dir", help="fold catalog directory (default: built-in catalog, or $ASG_FOLD_DIR)")
    p.add_argument("--wicket-dir", dest="wicket_dir", help="wicket catalog directory (default: built-in catalog, or $ASG_WICKET_DIR)")


def _cmd_manifest_show(args: argparse.Namespace) -> int:
    manifest_path = _manifest_path(args)
    try:
        manifest = load_manifest_file(manifest_path)
        resolved = resolve_manifest(manifest, fold_catalog_dir=_fold_dir(args), wicket_catalog_dir=_wicket_dir(args))
    except PolicyManifestError as exc:
        print(f"FAIL {exc.reason}: {exc}", file=sys.stderr)
        return 1

    print(f"manifest {resolved.manifest.manifest_id}  {resolved.manifest_digest}")
    print(f"  source: {manifest_path}")
    for ref in resolved.manifest.folds:
        print(f"  fold    {ref.fold_id:<24} {ref.digest}  OK")
    for ref in resolved.manifest.wickets:
        print(f"  wicket  {ref.wicket_id:<24} {ref.digest}  OK")
    return 0


def _cmd_manifest_activate(args: argparse.Namespace) -> int:
    manifest_path = _manifest_path(args)
    try:
        manifest = load_manifest_file(manifest_path)
        resolved = resolve_manifest(manifest, fold_catalog_dir=_fold_dir(args), wicket_catalog_dir=_wicket_dir(args))
    except PolicyManifestError as exc:
        print(f"FAIL {exc.reason}: {exc}", file=sys.stderr)
        return 1

    if not args.ledger:
        print("capsule manifest activate: --ledger is required (a store directory -- created if missing)", file=sys.stderr)
        return 2

    store = LedgerStore(Path(args.ledger))
    try:
        previous = find_latest_activation(store)
        capsule = build_manifest_activation_capsule(
            resolved=resolved,
            operator=args.operator,
            developer=args.developer,
            signer=_signer_from_env(),
            previous_activation_capsule_id=previous.capsule_id if previous is not None else None,
        )
        store.append(capsule, consequential=False)
    finally:
        store.close()

    print(f"activated manifest {resolved.manifest.manifest_id}  {resolved.manifest_digest}")
    print(f"  capsule {capsule['capsule_id']}")
    if previous is not None:
        print(f"  chained to previous activation {previous.capsule_id}")
    return 0


def _cmd_manifest_verify(args: argparse.Namespace) -> int:
    ledger_path = require_ledger_path("manifest verify", args)
    if ledger_path is None:
        return 2

    manifest_path = _manifest_path(args)
    try:
        manifest = load_manifest_file(manifest_path)
        resolved = resolve_manifest(manifest, fold_catalog_dir=_fold_dir(args), wicket_catalog_dir=_wicket_dir(args))
    except PolicyManifestError as exc:
        print(f"FAIL {exc.reason}: {exc}", file=sys.stderr)
        return 1

    with open_ledger(ledger_path) as store:
        record = store.fetch(args.capsule)
        if record is None:
            print(f"capsule manifest verify: no such capsule {args.capsule!r} in ledger {ledger_path}", file=sys.stderr)
            return 1

    cited = (record.capsule.get("asg_payload") or {}).get("manifest_digest")
    if cited is None:
        print(f"FAIL: capsule {record.capsule_id[:16]}… cites no manifest_digest", file=sys.stderr)
        return 1

    if cited != resolved.manifest_digest:
        print(
            f"FAIL: capsule cites manifest_digest {cited}, but {manifest_path} "
            f"({resolved.manifest.manifest_id}) resolves to {resolved.manifest_digest}",
            file=sys.stderr,
        )
        return 1

    print(
        f"OK: capsule {record.capsule_id[:16]}… was decided under manifest "
        f"{resolved.manifest.manifest_id}  {resolved.manifest_digest} (loaded from {manifest_path}, "
        "every cited fold/wicket digest still matches its catalog)"
    )
    return 0


def add_parser(sub: argparse._SubParsersAction) -> argparse.ArgumentParser:
    manifest = sub.add_parser("manifest", help="policy manifest: show/activate/verify (declare-attest-verify)")
    manifest_sub = manifest.add_subparsers(dest="manifest_command")
    manifest.set_defaults(manifest_parser=manifest)

    p_show = manifest_sub.add_parser("show", help="resolve a manifest against the real catalogs and print its digest")
    _add_resolve_args(p_show)
    p_show.set_defaults(func=_cmd_manifest_show)

    p_activate = manifest_sub.add_parser(
        "activate", help="append a signed config-change record citing the manifest's digest"
    )
    _add_resolve_args(p_activate)
    p_activate.add_argument("--ledger", help="ledger store directory (created if missing; not a JSONL fixture)")
    p_activate.add_argument("--operator", required=True, help="operator recorded on the activation record")
    p_activate.add_argument("--developer", required=True, help="developer/agent recorded on the activation record")
    p_activate.set_defaults(func=_cmd_manifest_activate)

    p_verify = manifest_sub.add_parser(
        "verify", help="confirm a decision capsule's cited manifest digest resolves to a real, loadable manifest"
    )
    _add_resolve_args(p_verify)
    p_verify.add_argument("--ledger", help="ledger store directory or a JSONL fixture file (default: $ASG_LEDGER)")
    p_verify.add_argument("--capsule", required=True, help="a capsule_id or an unambiguous prefix")
    p_verify.set_defaults(func=_cmd_manifest_verify)

    return manifest
