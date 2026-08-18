# SPDX-License-Identifier: Apache-2.0
"""``capsule enforce --pack <name>``: human acceptance transitions a pack
from observe to enforce mode.

Distinct from the existing ``capsule guard enforce`` (a local telemetry
marker only, ``guard_cmds.py``'s own docstring) -- this command performs a
real, substantive transition: the accepted thresholds (``--proposals``,
from ``capsule thresholds propose --out``) are merged into the pack's caps
wicket, the pack is re-installed with ``mode="enforce"`` (``packs/enforce.py``),
and -- when ``--ledger`` is given -- the transition is recorded as a signed
``policy_manifest_activated`` event, chained to the install's prior
activation. From this point, a caller building its ``GuardEngine`` from the
new manifest and passing ``dry_run=False`` (per the manifest's own
``PackRef.mode``) actually gates traffic under the accepted caps.
"""
from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

from ..envcompat import env_get
from ..guards.signing import LocalSigner
from ..ledger import LedgerStore
from ..packs import (
    PackDefinitionError,
    enforce_pack,
    load_pack_dir,
    load_proposals_file,
    record_pack_activation,
)
from .init_cmds import (
    _KEY_ID_ENV,
    _SECRET_ENV,
    BUILTIN_PACK_CATALOG_DIR,
)

__all__ = ["add_parser"]


def _cmd_enforce(args: argparse.Namespace) -> int:
    catalog_dir = Path(args.pack_catalog_dir) if args.pack_catalog_dir else BUILTIN_PACK_CATALOG_DIR
    pack_dir = catalog_dir / args.pack
    try:
        pack = load_pack_dir(pack_dir)
    except PackDefinitionError as exc:
        print(f"capsule enforce: pack {args.pack!r} failed to load ({exc.reason}): {exc}", file=sys.stderr)
        return 1

    try:
        proposals_pack_id, proposals = load_proposals_file(args.proposals)
    except PackDefinitionError as exc:
        print(f"capsule enforce: proposals file failed to load ({exc.reason}): {exc}", file=sys.stderr)
        return 1
    if proposals_pack_id != pack.pack_id:
        print(
            f"capsule enforce: {args.proposals} was generated for pack {proposals_pack_id!r}, "
            f"not {pack.pack_id!r} -- refusing to apply another pack's proposals",
            file=sys.stderr,
        )
        return 1

    accepted = {p["action_class"]: p["proposed_cap_minor"] for p in proposals}

    project_dir = Path(args.project_dir)
    try:
        installed = enforce_pack(pack, project_dir=project_dir, accepted=accepted)
    except ValueError as exc:
        print(f"capsule enforce: {exc}", file=sys.stderr)
        return 1

    print(f"enforced {pack.pack_id} -- accepted thresholds now gate traffic")
    for action_class, cap_minor in sorted(accepted.items()):
        print(f"  {action_class}: cap_minor={cap_minor}")
    print(f"  manifest:      {installed.manifest_path}")
    print(f"  manifest digest: {installed.resolved.manifest_digest}")
    print(
        "your integration must now build its GuardEngine from this manifest and call "
        "check(..., dry_run=False) to actually gate traffic -- this command does not itself "
        "run anything against live traffic."
    )

    if not args.ledger:
        print()
        print("no --ledger given: manifest written to disk only, no activation capsule recorded")
        return 0

    key_id = args.key_id or env_get(_KEY_ID_ENV)
    secret_text = args.secret or env_get(_SECRET_ENV)
    generated_secret = secret_text is None
    if key_id is None:
        key_id = f"{args.operator}-pack-enforce-key"
    if secret_text is None:
        secret_text = secrets.token_hex(32)
    signer = LocalSigner(key_id=key_id, secret=secret_text.encode("utf-8"))

    ledger = LedgerStore(args.ledger)
    try:
        capsule = record_pack_activation(
            installed, ledger=ledger, operator=args.operator, developer=args.developer, signer=signer
        )
    finally:
        ledger.close()

    print()
    print(f"activation recorded: {capsule['capsule_id']}")
    if generated_secret:
        print(f"  export {_KEY_ID_ENV}={key_id}")
        print(f"  export {_SECRET_ENV}={secret_text}")
    return 0


def add_parser(sub: argparse._SubParsersAction) -> argparse.ArgumentParser:
    p_enforce = sub.add_parser(
        "enforce", help="transition a pack from observe to enforce mode (accepted thresholds now gate traffic)"
    )
    p_enforce.add_argument("--pack", required=True, help="pack name, e.g. payments-safety (built-in catalog)")
    p_enforce.add_argument(
        "--pack-catalog-dir", default=None, help="override the built-in pack catalog directory (mainly for tests)"
    )
    p_enforce.add_argument(
        "--proposals", required=True, help="proposals YAML file (from `capsule thresholds propose --out`) to accept"
    )
    p_enforce.add_argument(
        "--project-dir", default=".", help="where .capsule/ was materialized by `capsule init`; default: cwd"
    )
    p_enforce.add_argument(
        "--ledger", default=None,
        help="ledger store directory to record this enforce transition's activation capsule into",
    )
    p_enforce.add_argument("--operator", default="local", help="operator identity for the activation capsule")
    p_enforce.add_argument("--developer", default="capsule-enforce-tool", help="developer identity for the activation capsule")
    p_enforce.add_argument("--key-id", default=None, help="signing key id for the activation capsule")
    p_enforce.add_argument("--secret", default=None, help="signing key secret")
    p_enforce.set_defaults(func=_cmd_enforce)
    return p_enforce
