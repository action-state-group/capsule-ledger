# SPDX-License-Identifier: Apache-2.0
"""Build and seal one external-system confirmation as a fulfillment capsule.

A fulfillment capsule never asserts that a third system's state change is
this codebase's own doing -- it is a passive, ``fyi``-typed record of what a
connector observed elsewhere (mirrors ``guards/capsule.py``'s
``build_event_capsule``, extended with the -02 Effect Record the event
builder deliberately omits). It is always chained (``chain.relation ==
"confirms"``, REGISTRY.md #6: "the most common chain link: *attempted ->
confirmed*") to the commitment capsule it confirms -- there is no standalone
fulfillment capsule, by construction.

``effect.effect_attestation`` is graded honestly per REGISTRY.md #5: a
connector read is the gate/engine recording a THIRD SYSTEM's claim about its
own state, not something the engine directly observed at its own effect
boundary (that would be ``gate_executed``). It is therefore never graded
above ``runtime_claimed`` here -- a stronger, counterparty-SIGNED grade is
the later paid-tier upgrade (ledger-lane outbox
``[ldg-confirm-ingester]``), not something a plain connector read can ever
claim for itself.

``effect.response_digest`` commits the connector's raw evidence (the IdP's
own flag record, a ticket's closure payload, a payment processor's receipt)
into the capsule the same way ``guards/capsule.py``'s ``ConstraintOutcome``
commits check evidence: digested only, never stored in the clear.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from agent_action_capsule import (
    AssuranceBlock,
    Capsule,
    Chain,
    EffectRecord,
    compute_capsule_id,
    derive_effect_mode,
    json_digest,
)

from ..guards.signing import Signer
from .errors import CONFIRM_INVALID_STATUS, ConfirmError

__all__ = ["CONFIRMS", "EFFECT_ATTESTATION_CONNECTOR_READ", "build_confirm_capsule"]

_SPEC_VERSION = "draft-mih-scitt-agent-action-capsule-02"
_FORMAT_VERSION = "2"

# The registered chain.relation a fulfillment capsule uses to cite the
# commitment it confirms (REGISTRY.md #6) -- non-terminal: the commitment's
# own open state is unaffected by a confirmation observing it.
CONFIRMS = "confirms"

# See module docstring: a connector read is graded no stronger than
# "runtime_claimed" (REGISTRY.md #5) -- the gate never itself observed the
# third system's effect boundary, only recorded its claim.
EFFECT_ATTESTATION_CONNECTOR_READ = "runtime_claimed"

_VALID_STATUSES = ("confirmed", "failed")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_confirm_capsule(
    *,
    commitment_capsule_id: str,
    operator: str,
    developer: str,
    connector_type: str,
    subject: str,
    predicate: str,
    status: str,
    external_ref: str,
    evidence: dict,
    signer: Signer,
    observed_at: str | None = None,
    action_id: str | None = None,
    manifest_digest: str | None = None,
) -> dict:
    """Sign and seal one fulfillment capsule.

    ``status`` MUST be ``"confirmed"`` or ``"failed"`` (never ``"planned"``/
    ``"dispatched"``) -- ingestion only ever records something the third
    system has already settled one way or the other; there is nothing to
    ingest a ``"planned"``/``"dispatched"`` state for; a poll that has not
    yet settled is a connector returning ``None``, not a call to this
    function (``ConfirmIngestEngine.ingest``, ``engine.py``).

    Requires a live ``signer`` -- callers MUST NOT call this when the
    signing key is unavailable (gating doc §1: "an unsigned record is not a
    record"); that fail-closed gate lives in ``ConfirmIngestEngine``, one
    layer up, same as every other builder in this codebase.
    """
    if status not in _VALID_STATUSES:
        raise ConfirmError(CONFIRM_INVALID_STATUS, f"confirm status must be one of {_VALID_STATUSES}, got {status!r}")

    response_digest = json_digest(evidence)
    effect = EffectRecord(
        status=status,
        type=predicate,
        response_digest=response_digest,
        external_ref=external_ref,
        effect_attestation=EFFECT_ATTESTATION_CONNECTOR_READ,
    )
    effect_mode = derive_effect_mode({"status": status, "response_digest": response_digest})

    verb = f"confirm.{predicate}"
    resolved_action_id = action_id or f"{verb}/{uuid.uuid4()}"
    timestamp = observed_at or _utc_now()

    chain = Chain(parent_capsule_id=commitment_capsule_id, relation=CONFIRMS)
    capsule_obj = Capsule(
        spec_version=_SPEC_VERSION,
        format_version=_FORMAT_VERSION,
        action_id=resolved_action_id,
        action_type="fyi",
        operator=operator,
        developer=developer,
        timestamp=timestamp,
        effect=effect,
        assurance=AssuranceBlock(attestation_mode="self_attested", effect_mode=effect_mode, ledger_mode="chained"),
        chain=chain,
    )
    body = capsule_obj.to_dict()
    asg_payload: dict = {"connector_type": connector_type, "subject": subject, "predicate": predicate}
    if manifest_digest is not None:
        asg_payload["manifest_digest"] = manifest_digest
    body["asg_payload"] = asg_payload

    # Same digest-then-sign-then-reseal sequence as every other capsule
    # builder in this codebase (guards/capsule.py, holds/capsules.py):
    # the signature is committed into the body before capsule_id is
    # computed, so a tampered signature is caught by digest_mismatch on
    # recompute rather than needing a separate verification step.
    presig_digest = json_digest(body)
    body["asg_signature"] = {"key_id": signer.key_id, "alg": signer.algorithm, "sig": signer.sign(presig_digest)}

    capsule_id = compute_capsule_id(body)
    sealed = {"spec_version": body["spec_version"], "format_version": body["format_version"], "capsule_id": capsule_id}
    for k, v in body.items():
        if k not in sealed:
            sealed[k] = v
    return sealed
