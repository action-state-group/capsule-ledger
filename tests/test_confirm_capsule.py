# SPDX-License-Identifier: Apache-2.0
"""``build_confirm_capsule``: the fulfillment-capsule builder itself, in
isolation from the ingest engine -- chaining, effect-attestation grading,
and the confirmed/failed status invariant."""
from __future__ import annotations

import pytest

from capsule_ledger.confirm.capsule import (
    CONFIRMS,
    EFFECT_ATTESTATION_CONNECTOR_READ,
    build_confirm_capsule,
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
        operator="acme-corp", developer="onboarding-agent@v1",
        connector_type="mock-idp", subject="user-42", predicate="mfa_enabled",
        status="confirmed", external_ref="idp-evt-001", evidence={"secret_flag_value": "xyz"},
        signer=signer, observed_at="2026-08-12T00:00:00Z",
    )
    payload = capsule["asg_payload"]
    assert payload == {"connector_type": "mock-idp", "subject": "user-42", "predicate": "mfa_enabled"}
    assert "secret_flag_value" not in str(payload)


def test_capsule_independently_verifies(store, signer):
    commitment = _commitment_capsule(signer)
    store.append(commitment)
    capsule = build_confirm_capsule(
        commitment_capsule_id=commitment["capsule_id"],
        operator="acme-corp", developer="onboarding-agent@v1",
        connector_type="mock-idp", subject="user-42", predicate="mfa_enabled",
        status="confirmed", external_ref="idp-evt-001", evidence={"enabled": True},
        signer=signer, observed_at="2026-08-12T00:00:00Z",
    )
    store.append(capsule)
    result = store.verify(capsule["capsule_id"])
    assert result.ok, result.findings
