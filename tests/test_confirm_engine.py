# SPDX-License-Identifier: Apache-2.0
"""``ConfirmIngestEngine``: pending/recorded/idempotent/fail-closed behavior
against a real ``LedgerStore``."""
from __future__ import annotations

from capsule_ledger.confirm import ConfirmIngestEngine, ConfirmStatus
from capsule_ledger.confirm.connectors import MockIdPConnector
from capsule_ledger.confirm.errors import CONFIRM_COMMITMENT_NOT_FOUND, CONFIRM_SIGNER_UNAVAILABLE
from capsule_ledger.guards import build_event_capsule
from capsule_ledger.guards.signing import SigningKeyUnavailable


def _commitment(store, signer):
    capsule = build_event_capsule(
        operator="acme-corp", developer="onboarding-agent@v1", signer=signer,
        event="intent.declare", detail={"predicate": "mfa_enabled"},
    )
    store.append(capsule)
    return capsule


def test_no_observation_yet_reports_pending_and_appends_nothing(store, signer):
    commitment = _commitment(store, signer)
    connector = MockIdPConnector()
    engine = ConfirmIngestEngine(ledger=store, connector=connector, signer_provider=lambda: signer)

    before = sum(1 for _ in store.scan())
    decision = engine.ingest(commitment["capsule_id"], subject="user-42", predicate="mfa_enabled")
    after = sum(1 for _ in store.scan())

    assert decision.status == ConfirmStatus.PENDING
    assert decision.capsule is None
    assert after == before


def test_settled_confirmation_appends_a_chained_fulfillment_capsule(store, signer):
    commitment = _commitment(store, signer)
    connector = MockIdPConnector()
    connector.set_state(
        subject="user-42", predicate="mfa_enabled", status="confirmed",
        external_ref="idp-evt-001", observed_at="2026-08-12T00:00:00Z",
    )
    engine = ConfirmIngestEngine(ledger=store, connector=connector, signer_provider=lambda: signer)

    decision = engine.ingest(commitment["capsule_id"], subject="user-42", predicate="mfa_enabled")

    assert decision.status == ConfirmStatus.RECORDED
    assert decision.effect_status == "confirmed"
    assert decision.capsule["chain"]["parent_capsule_id"] == commitment["capsule_id"]
    assert decision.capsule["chain"]["relation"] == "confirms"

    result = store.verify(decision.capsule["capsule_id"])
    assert result.ok, result.findings


def test_reingesting_the_same_external_ref_is_idempotent(store, signer):
    commitment = _commitment(store, signer)
    connector = MockIdPConnector()
    connector.set_state(
        subject="user-42", predicate="mfa_enabled", status="confirmed",
        external_ref="idp-evt-001", observed_at="2026-08-12T00:00:00Z",
    )
    engine = ConfirmIngestEngine(ledger=store, connector=connector, signer_provider=lambda: signer)

    first = engine.ingest(commitment["capsule_id"], subject="user-42", predicate="mfa_enabled")
    second = engine.ingest(commitment["capsule_id"], subject="user-42", predicate="mfa_enabled")

    assert first.status == ConfirmStatus.RECORDED
    assert second.status == ConfirmStatus.ALREADY_RECORDED
    assert second.capsule["capsule_id"] == first.capsule["capsule_id"]

    fulfillment_capsules = [
        r.capsule for r in store.scan()
        if (r.capsule.get("chain") or {}).get("parent_capsule_id") == commitment["capsule_id"]
    ]
    assert len(fulfillment_capsules) == 1


def test_commitment_not_found_errors_without_appending(store, signer):
    connector = MockIdPConnector()
    connector.set_state(
        subject="user-42", predicate="mfa_enabled", status="confirmed",
        external_ref="idp-evt-001", observed_at="2026-08-12T00:00:00Z",
    )
    engine = ConfirmIngestEngine(ledger=store, connector=connector, signer_provider=lambda: signer)

    before = sum(1 for _ in store.scan())
    decision = engine.ingest("a" * 64, subject="user-42", predicate="mfa_enabled")
    after = sum(1 for _ in store.scan())

    assert decision.status == ConfirmStatus.ERROR
    assert decision.reason_code == CONFIRM_COMMITMENT_NOT_FOUND
    assert decision.capsule is None
    assert after == before


def test_signer_unavailable_fails_closed_without_appending(store, signer):
    commitment = _commitment(store, signer)
    connector = MockIdPConnector()
    connector.set_state(
        subject="user-42", predicate="mfa_enabled", status="confirmed",
        external_ref="idp-evt-001", observed_at="2026-08-12T00:00:00Z",
    )

    def _no_signer():
        raise SigningKeyUnavailable()

    engine = ConfirmIngestEngine(ledger=store, connector=connector, signer_provider=_no_signer)

    before = sum(1 for _ in store.scan())
    decision = engine.ingest(commitment["capsule_id"], subject="user-42", predicate="mfa_enabled")
    after = sum(1 for _ in store.scan())

    assert decision.status == ConfirmStatus.ERROR
    assert decision.reason_code == CONFIRM_SIGNER_UNAVAILABLE
    assert decision.capsule is None
    assert after == before  # fail closed: nothing recorded, not even a partial capsule


def test_failed_confirmation_is_recorded_honestly(store, signer):
    commitment = _commitment(store, signer)
    connector = MockIdPConnector()
    connector.set_state(
        subject="user-42", predicate="mfa_enabled", status="failed",
        external_ref="idp-evt-002", observed_at="2026-08-12T00:00:00Z",
    )
    engine = ConfirmIngestEngine(ledger=store, connector=connector, signer_provider=lambda: signer)

    decision = engine.ingest(commitment["capsule_id"], subject="user-42", predicate="mfa_enabled")

    assert decision.status == ConfirmStatus.RECORDED
    assert decision.effect_status == "failed"
    assert decision.capsule["effect"]["status"] == "failed"
