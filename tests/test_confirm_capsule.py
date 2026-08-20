# SPDX-License-Identifier: Apache-2.0
"""``build_confirm_capsule``: the fulfillment-capsule builder itself, in
isolation from the ingest engine -- chaining, effect-attestation grading,
and the confirmed/failed status invariant."""
from __future__ import annotations

import pytest

from capsule_ledger.confirm.capsule import (
    COMMITMENT_TYPE_CONFIRMATION,
    COMMITMENT_TYPE_ORIGIN,
    CONFIRMS,
    EFFECT_ATTESTATION_CONNECTOR_READ,
    build_confirm_capsule,
    commitment_type_label,
)
from capsule_ledger.confirm.errors import CONFIRM_INVALID_STATUS, ConfirmError
from capsule_ledger.guards import build_event_capsule


def _commitment_capsule(signer):
    return build_event_capsule(
        operator="acme-corp", developer="onboarding-agent@v1", signer=signer,
        event="intent.declare", detail={"predicate": "mfa_enabled"},
    )


def test_confirmed_capsule_chains_to_commitment_with_confirms_relation(signer):
    commitment = _commitment_capsule(signer)
    capsule = build_confirm_capsule(
        commitment_capsule_id=commitment["capsule_id"],
        commitment_type=COMMITMENT_TYPE_ORIGIN,
        operator="acme-corp", developer="onboarding-agent@v1",
        connector_type="mock-idp", subject="user-42", predicate="mfa_enabled",
        status="confirmed", external_ref="idp-evt-001", evidence={"enabled": True},
        signer=signer, observed_at="2026-08-12T00:00:00Z",
    )
    assert capsule["chain"] == {"parent_capsule_id": commitment["capsule_id"], "relation": CONFIRMS}


def test_confirmed_capsule_effect_record_is_honest(signer):
    commitment = _commitment_capsule(signer)
    capsule = build_confirm_capsule(
        commitment_capsule_id=commitment["capsule_id"],
        commitment_type=COMMITMENT_TYPE_ORIGIN,
        operator="acme-corp", developer="onboarding-agent@v1",
        connector_type="mock-idp", subject="user-42", predicate="mfa_enabled",
        status="confirmed", external_ref="idp-evt-001", evidence={"enabled": True},
        signer=signer, observed_at="2026-08-12T00:00:00Z",
    )
    effect = capsule["effect"]
    assert effect["status"] == "confirmed"
    assert effect["type"] == "mfa_enabled"
    assert effect["external_ref"] == "idp-evt-001"
    assert effect["effect_attestation"] == EFFECT_ATTESTATION_CONNECTOR_READ == "runtime_claimed"
    # response_digest commits the evidence -- never stored in the clear.
    assert len(effect["response_digest"]) == 64
    assert "enabled" not in capsule.get("asg_payload", {})  # evidence dict itself never lands in asg_payload
    # A connector read is never graded as strong as gate_executed.
    assert effect["effect_attestation"] != "gate_executed"

    assurance = capsule["assurance"]
    assert assurance["effect_mode"] == "confirmed"
    assert assurance["ledger_mode"] == "chained"
    assert assurance["attestation_mode"] == "self_attested"


def test_failed_status_derives_dispatched_unconfirmed(signer):
    commitment = _commitment_capsule(signer)
    capsule = build_confirm_capsule(
        commitment_capsule_id=commitment["capsule_id"],
        commitment_type=COMMITMENT_TYPE_ORIGIN,
        operator="acme-corp", developer="onboarding-agent@v1",
        connector_type="mock-idp", subject="user-42", predicate="mfa_enabled",
        status="failed", external_ref="idp-evt-002", evidence={"enabled": False},
        signer=signer, observed_at="2026-08-12T00:00:00Z",
    )
    assert capsule["effect"]["status"] == "failed"
    assert capsule["assurance"]["effect_mode"] == "dispatched_unconfirmed"


@pytest.mark.parametrize("bad_status", ["planned", "dispatched", "pending", ""])
def test_invalid_status_rejected(signer, bad_status):
    commitment = _commitment_capsule(signer)
    with pytest.raises(ConfirmError) as exc:
        build_confirm_capsule(
            commitment_capsule_id=commitment["capsule_id"],
            commitment_type=COMMITMENT_TYPE_ORIGIN,
            operator="acme-corp", developer="onboarding-agent@v1",
            connector_type="mock-idp", subject="user-42", predicate="mfa_enabled",
            status=bad_status, external_ref="idp-evt-003", evidence={},
            signer=signer, observed_at="2026-08-12T00:00:00Z",
        )
    assert exc.value.reason == CONFIRM_INVALID_STATUS


def test_asg_payload_carries_connector_context_not_evidence(signer):
    commitment = _commitment_capsule(signer)
    capsule = build_confirm_capsule(
        commitment_capsule_id=commitment["capsule_id"],
        commitment_type=COMMITMENT_TYPE_ORIGIN,
        operator="acme-corp", developer="onboarding-agent@v1",
        connector_type="mock-idp", subject="user-42", predicate="mfa_enabled",
        status="confirmed", external_ref="idp-evt-001", evidence={"secret_flag_value": "xyz"},
        signer=signer, observed_at="2026-08-12T00:00:00Z",
    )
    payload = capsule["asg_payload"]
    assert payload == {
        "connector_type": "mock-idp",
        "subject": "user-42",
        "predicate": "mfa_enabled",
        "commitment_type": COMMITMENT_TYPE_ORIGIN,
    }
    assert "secret_flag_value" not in str(payload)


def test_capsule_independently_verifies(store, signer):
    commitment = _commitment_capsule(signer)
    store.append(commitment)
    capsule = build_confirm_capsule(
        commitment_capsule_id=commitment["capsule_id"],
        commitment_type=COMMITMENT_TYPE_ORIGIN,
        operator="acme-corp", developer="onboarding-agent@v1",
        connector_type="mock-idp", subject="user-42", predicate="mfa_enabled",
        status="confirmed", external_ref="idp-evt-001", evidence={"enabled": True},
        signer=signer, observed_at="2026-08-12T00:00:00Z",
    )
    store.append(capsule)
    result = store.verify(capsule["capsule_id"])
    assert result.ok, result.findings


# --- Finding C (delta-adversarial-report SCOPE 2): commitment-type labeling ---


def test_commitment_type_label_origin_for_a_fresh_intent_capsule(signer):
    commitment = _commitment_capsule(signer)
    assert commitment_type_label(commitment) == COMMITMENT_TYPE_ORIGIN


def test_commitment_type_label_origin_for_a_confirms_relation_from_another_module(signer):
    """chain.relation == "confirms" is shared registry vocabulary -- other
    modules use it for their own, unrelated parent links (e.g. a judgment
    capsule chained to its session-close capsule, judge/capsules.py). Only
    a real fulfillment capsule (asg_payload.connector_type present) should
    ever be labeled "confirmation"."""
    parent = _commitment_capsule(signer)
    look_alike = build_event_capsule(
        operator="acme-corp", developer="onboarding-agent@v1", signer=signer,
        event="judge.judgment", detail={"label": "agreement_reached"},
        chain_parent=parent["capsule_id"], chain_relation=CONFIRMS,
    )
    assert look_alike["chain"]["relation"] == CONFIRMS
    assert "connector_type" not in look_alike.get("asg_payload", {})
    assert commitment_type_label(look_alike) == COMMITMENT_TYPE_ORIGIN


def test_commitment_type_label_confirmation_for_a_prior_fulfillment(signer):
    commitment = _commitment_capsule(signer)
    fulfillment = build_confirm_capsule(
        commitment_capsule_id=commitment["capsule_id"],
        commitment_type=COMMITMENT_TYPE_ORIGIN,
        operator="acme-corp", developer="onboarding-agent@v1",
        connector_type="mock-idp", subject="user-42", predicate="mfa_enabled",
        status="confirmed", external_ref="idp-evt-001", evidence={"enabled": True},
        signer=signer, observed_at="2026-08-12T00:00:00Z",
    )
    # the fulfillment itself is now used as the anchor for a second ingestion:
    assert commitment_type_label(fulfillment) == COMMITMENT_TYPE_CONFIRMATION


def test_commitment_type_recorded_on_the_sealed_capsule(signer):
    commitment = _commitment_capsule(signer)
    fulfillment = build_confirm_capsule(
        commitment_capsule_id=commitment["capsule_id"],
        commitment_type=commitment_type_label(commitment),
        operator="acme-corp", developer="onboarding-agent@v1",
        connector_type="mock-idp", subject="user-42", predicate="mfa_enabled",
        status="confirmed", external_ref="idp-evt-001", evidence={"enabled": True},
        signer=signer, observed_at="2026-08-12T00:00:00Z",
    )
    assert fulfillment["asg_payload"]["commitment_type"] == COMMITMENT_TYPE_ORIGIN

    laundered = build_confirm_capsule(
        commitment_capsule_id=fulfillment["capsule_id"],
        commitment_type=commitment_type_label(fulfillment),
        operator="acme-corp", developer="onboarding-agent@v1",
        connector_type="mock-idp", subject="user-42", predicate="mfa_enabled",
        status="confirmed", external_ref="idp-evt-002", evidence={"enabled": True},
        signer=signer, observed_at="2026-08-12T00:05:00Z",
    )
    # readable directly off the record -- no second ledger scan needed to see
    # this fulfillment is chained to a PRIOR fulfillment, not a fresh commitment:
    assert laundered["asg_payload"]["commitment_type"] == COMMITMENT_TYPE_CONFIRMATION


def test_commitment_type_mutant_relation_only_check_false_positives(signer, monkeypatch):
    """RED-WITH-MUTANT: if commitment_type_label used chain.relation ==
    CONFIRMS alone (dropping the asg_payload.connector_type check), the
    judge-module look-alike above -- a legitimate origin capsule that
    happens to share the "confirms" relation for an unrelated reason --
    would be mislabeled "confirmation". The GREEN assertion above would
    fail."""
    import capsule_ledger.confirm.capsule as confirm_cap_module

    def _mutant_label(commitment_capsule):
        anchor_chain = commitment_capsule.get("chain") or {}
        if anchor_chain.get("relation") == confirm_cap_module.CONFIRMS:
            return confirm_cap_module.COMMITMENT_TYPE_CONFIRMATION
        return confirm_cap_module.COMMITMENT_TYPE_ORIGIN

    monkeypatch.setattr(confirm_cap_module, "commitment_type_label", _mutant_label)

    parent = _commitment_capsule(signer)
    look_alike = build_event_capsule(
        operator="acme-corp", developer="onboarding-agent@v1", signer=signer,
        event="judge.judgment", detail={"label": "agreement_reached"},
        chain_parent=parent["capsule_id"], chain_relation=CONFIRMS,
    )
    # RED: a legitimate origin capsule is falsely labeled "confirmation"
    # under the relation-only mutant -- proves the connector_type condition
    # in the real code is load-bearing, not redundant.
    assert confirm_cap_module.commitment_type_label(look_alike) == COMMITMENT_TYPE_CONFIRMATION


def test_commitment_type_mutant_hardcoded_origin_hides_laundering(signer, monkeypatch):
    """RED-WITH-MUTANT: if the caller hardcoded commitment_type="origin"
    instead of computing it from the actual anchor capsule (skipping
    commitment_type_label entirely -- exactly what a caller could do since
    the parameter takes any string), a fulfillment-chained-to-fulfillment
    would look identical to a normal origin-anchored chain on the record.
    The GREEN assertion above -- that the laundered capsule is labeled
    "confirmation" -- would fail this way."""
    commitment = _commitment_capsule(signer)
    fulfillment = build_confirm_capsule(
        commitment_capsule_id=commitment["capsule_id"],
        commitment_type=COMMITMENT_TYPE_ORIGIN,
        operator="acme-corp", developer="onboarding-agent@v1",
        connector_type="mock-idp", subject="user-42", predicate="mfa_enabled",
        status="confirmed", external_ref="idp-evt-001", evidence={"enabled": True},
        signer=signer, observed_at="2026-08-12T00:00:00Z",
    )

    # MUTANT: skip commitment_type_label, hardcode "origin" regardless of the
    # anchor's real chain state -- the pre-Finding-C shape.
    laundered = build_confirm_capsule(
        commitment_capsule_id=fulfillment["capsule_id"],
        commitment_type=COMMITMENT_TYPE_ORIGIN,  # should have been "confirmation"
        operator="acme-corp", developer="onboarding-agent@v1",
        connector_type="mock-idp", subject="user-42", predicate="mfa_enabled",
        status="confirmed", external_ref="idp-evt-002", evidence={"enabled": True},
        signer=signer, observed_at="2026-08-12T00:05:00Z",
    )
    # RED: the laundered chain is now indistinguishable from a normal one --
    # proves the GREEN test above is meaningful, not a tautology.
    assert laundered["asg_payload"]["commitment_type"] == COMMITMENT_TYPE_ORIGIN
    assert commitment_type_label(fulfillment) == COMMITMENT_TYPE_CONFIRMATION  # the truth, unused by the mutant call


# --- Finding D (delta-adversarial-report SCOPE 2, by design): freshness ---


def test_stale_observed_at_recorded_honestly_not_reordered(signer):
    """The ingester is a passive recorder, not a freshness gate: a stale
    observed_at (far in the past) is recorded exactly as reported -- never
    clamped to "now" -- and never causes an upgraded assurance grade. The
    grade (runtime_claimed) is the signal an operator reads."""
    commitment = _commitment_capsule(signer)
    capsule = build_confirm_capsule(
        commitment_capsule_id=commitment["capsule_id"],
        commitment_type=COMMITMENT_TYPE_ORIGIN,
        operator="acme-corp", developer="onboarding-agent@v1",
        connector_type="mock-idp", subject="user-42", predicate="mfa_enabled",
        status="confirmed", external_ref="idp-evt-stale", evidence={"enabled": True},
        signer=signer, observed_at="2020-01-01T00:00:00Z",
    )
    assert capsule["timestamp"] == "2020-01-01T00:00:00Z"
    assert capsule["effect"]["effect_attestation"] == "runtime_claimed"


def test_stale_observed_at_mutant_silently_clamped_to_now(signer, monkeypatch):
    """RED-WITH-MUTANT: if _resolve_timestamp silently clamped a stale
    observed_at to "now" instead of recording it verbatim (a plausible
    "freshness fix" someone might add later), the GREEN assertion above --
    that the sealed capsule's timestamp matches exactly what the third
    system reported -- would fail."""
    import capsule_ledger.confirm.capsule as confirm_cap_module

    fixed_now = "2026-08-18T00:00:00Z"
    # MUTANT: ignore observed_at entirely, always report "now" -- the
    # silent-reorder behavior Finding D's docs explicitly rule out.
    monkeypatch.setattr(confirm_cap_module, "_resolve_timestamp", lambda observed_at: fixed_now)

    commitment = _commitment_capsule(signer)
    capsule = build_confirm_capsule(
        commitment_capsule_id=commitment["capsule_id"],
        commitment_type=COMMITMENT_TYPE_ORIGIN,
        operator="acme-corp", developer="onboarding-agent@v1",
        connector_type="mock-idp", subject="user-42", predicate="mfa_enabled",
        status="confirmed", external_ref="idp-evt-stale-mut", evidence={"enabled": True},
        signer=signer, observed_at="2020-01-01T00:00:00Z",
    )
    # RED: the stale timestamp the third system actually reported is gone,
    # silently replaced with "now" -- proves the GREEN test above is real.
    assert capsule["timestamp"] == fixed_now
    assert capsule["timestamp"] != "2020-01-01T00:00:00Z"
