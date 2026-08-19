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
above ``runtime_claimed`` here.

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

__all__ = [
    "CONFIRMS",
    "EFFECT_ATTESTATION_CONNECTOR_READ",
    "COMMITMENT_TYPE_ORIGIN",
    "COMMITMENT_TYPE_CONFIRMATION",
    "commitment_type_label",
    "build_confirm_capsule",
]

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

# Finding C (delta-adversarial-report SCOPE 2, 2026-08-18): the engine
# accepts ANY existing capsule_id as the commitment anchor -- by design,
# docs/confirm-connector-interface.md's "any capsule with a capsule_id" --
# so a fulfillment chained to a PRIOR fulfillment (rather than a fresh
# commitment) is not rejected. It is labeled instead: never silently
# indistinguishable from a normal origin-commitment chain, readable
# directly off the new capsule's own asg_payload without a second ledger
# scan.
COMMITMENT_TYPE_ORIGIN = "origin"
COMMITMENT_TYPE_CONFIRMATION = "confirmation"


def commitment_type_label(commitment_capsule: dict) -> str:
    """Classify the commitment anchor's own chain state (Finding C).

    ``COMMITMENT_TYPE_CONFIRMATION`` when the capsule being cited as a
    commitment is itself a prior *fulfillment* capsule produced by this
    module -- the laundering shape the adversarial pass found accepted
    without complaint. ``COMMITMENT_TYPE_ORIGIN`` otherwise.

    ``chain.relation == CONFIRMS`` alone is NOT a reliable fulfillment
    marker: it's shared, registry-level vocabulary ("the most common chain
    link: attempted -> confirmed") that other modules use for their own,
    unrelated parent links (e.g. ``judge/capsules.py`` chains a judgment
    capsule to its session-close capsule with the same relation). The
    reliable signal, already established by
    ``examples/conversation_outcome_demo.py``'s own fulfillment lookup, is
    the combination: ``chain.relation == CONFIRMS`` *and*
    ``asg_payload.connector_type`` present -- only ``build_confirm_capsule``
    ever sets that field. This does not change what the engine accepts; it
    changes what the record says about what it accepted.
    """
    anchor_chain = commitment_capsule.get("chain") or {}
    anchor_payload = commitment_capsule.get("asg_payload") or {}
    if anchor_chain.get("relation") == CONFIRMS and anchor_payload.get("connector_type"):
        return COMMITMENT_TYPE_CONFIRMATION
    return COMMITMENT_TYPE_ORIGIN


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _resolve_timestamp(observed_at: str | None) -> str:
    """The capsule's own ``timestamp`` is the connector's ``observed_at``
    verbatim when given -- recorded honestly, never clamped to "now" and
    never reordered for being stale (Finding D, delta-adversarial-report
    SCOPE 2: freshness/ordering is deliberately not this layer's gate; the
    ``runtime_claimed`` grade is the signal an operator reads, and silently
    "fixing" a stale timestamp would hide that signal instead of surfacing
    it). An operator who needs a freshness requirement enforces it at the
    connector or CLI layer, upstream of this function -- see
    docs/confirm-connector-interface.md. Falls back to the current time
    only when the connector reports no ``observed_at`` at all.
    """
    return observed_at or _utc_now()


def build_confirm_capsule(
    *,
    commitment_capsule_id: str,
    commitment_type: str,
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

    ``commitment_type`` is required, not defaulted -- ``commitment_type_label``
    computes it from the anchor capsule the caller already fetched, so
    there is no code path that silently records ``"origin"`` for an anchor
    nobody checked (Finding C).

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
    timestamp = _resolve_timestamp(observed_at)

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
    asg_payload: dict = {
        "connector_type": connector_type,
        "subject": subject,
        "predicate": predicate,
        "commitment_type": commitment_type,
    }
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
