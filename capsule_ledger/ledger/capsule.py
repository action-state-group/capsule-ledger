# SPDX-License-Identifier: Apache-2.0
"""``build_event_capsule``: seal a passive administrative record (a
degradation/recovery event, an operator alert, a signing-key rotation) as
an Agent Action Capsule. ``action_type: "fyi"`` per the reference library's
own convention -- passive observation, never a gate decision.

This is mechanical ledger-side plumbing (construct + sign), not a guard
decision: ``build_decision_capsule``/``ALLOW``/``DENY``/``ESCALATE`` and the
rest of the guard-decision surface dissolved to capsule-engine at W3.2
(#127) and stay there -- this repo must not re-import or re-implement that.
``build_event_capsule`` survives here because ``cli/key_cmds.py``'s ``capsule
key rotate`` is real, live ledger functionality (signing/revocation stayed
in ledger -> cll, #126), and needs a capsule to seal the rotation event
into; ``tests/test_key_rotation.py`` and ``tests/test_checkpoint.py`` use
the same function for the same reason, not as a test-only stand-in.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from agent_action_capsule import AssuranceBlock, Capsule, Chain, compute_capsule_id, json_digest

from .signing import Signer

__all__ = ["build_event_capsule"]


def _new_action_id(verb: str) -> str:
    return f"{verb}/{uuid.uuid4()}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_event_capsule(
    *,
    operator: str,
    developer: str,
    signer: Signer,
    event: str,
    detail: dict,
    timestamp: str | None = None,
    action_id: str | None = None,
    chain_parent: str | None = None,
    chain_relation: str | None = None,
) -> dict:
    """Build, sign, and seal a passive ``fyi`` event capsule. Requires a
    live ``signer`` -- an unsigned record is not a record."""
    resolved_action_id = action_id or _new_action_id(event)
    resolved_timestamp = timestamp or _utc_now()
    chain = Chain(parent_capsule_id=chain_parent, relation=chain_relation) if chain_parent else None
    capsule_obj = Capsule(
        spec_version="draft-mih-scitt-agent-action-capsule-02",
        format_version="2",
        action_id=resolved_action_id,
        action_type="fyi",
        operator=operator,
        developer=developer,
        timestamp=resolved_timestamp,
        assurance=AssuranceBlock(
            attestation_mode="self_attested",
            effect_mode="not_applicable",
            ledger_mode="chained" if chain is not None else "standalone",
        ),
        chain=chain,
    )
    body = capsule_obj.to_dict()
    body["asg_payload"] = {"event": event, "detail": detail}

    presig_digest = json_digest(body)
    body["asg_signature"] = {
        "key_id": signer.key_id,
        "alg": signer.algorithm,
        "sig": signer.sign(presig_digest),
    }

    capsule_id = compute_capsule_id(body)
    sealed = {"spec_version": body["spec_version"], "format_version": body["format_version"], "capsule_id": capsule_id}
    for k, v in body.items():
        if k not in sealed:
            sealed[k] = v
    return sealed
