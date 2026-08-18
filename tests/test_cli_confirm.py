# SPDX-License-Identifier: Apache-2.0
"""``capsule confirm ingest``: CLI wrapper over ``ConfirmIngestEngine`` +
``MockIdPConnector``."""
from __future__ import annotations

import pytest

from capsule_ledger.cli.main import main
from capsule_ledger.guards import LocalSigner, build_event_capsule
from capsule_ledger.ledger import LedgerStore


@pytest.fixture(autouse=True)
def _full_arm(monkeypatch):
    # confirm is registered only in the "full" packaging arm (its whole job
    # is producing a fulfillment *capsule*) -- pin it regardless of the host
    # environment so these tests don't depend on ambient env vars.
    monkeypatch.delenv("CAPSULE_LEDGER_ARM", raising=False)
    monkeypatch.delenv("CAPSULE_LEDGER_ARM", raising=False)


def _seed_commitment(ledger_dir):
    store = LedgerStore(ledger_dir)
    try:
        signer = LocalSigner(key_id="test-key", secret=b"test-secret")
        capsule = build_event_capsule(
            operator="acme-corp", developer="onboarding-agent@v1", signer=signer,
            event="intent.declare", detail={"predicate": "mfa_enabled"},
        )
        store.append(capsule)
        return capsule["capsule_id"]
    finally:
        store.close()


def test_confirm_ingest_pending_when_status_omitted(tmp_path, capsys):
    ledger_dir = tmp_path / "ledger"
    commitment_id = _seed_commitment(ledger_dir)

    rc = main(
        [
            "confirm", "ingest",
            "--ledger", str(ledger_dir),
            "--commitment", commitment_id,
            "--subject", "user-42", "--predicate", "mfa_enabled",
            "--key-id", "test-key", "--secret", "test-secret",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "pending" in out


def test_confirm_ingest_records_a_fulfillment_capsule(tmp_path, capsys):
    ledger_dir = tmp_path / "ledger"
    commitment_id = _seed_commitment(ledger_dir)

    rc = main(
        [
            "confirm", "ingest",
            "--ledger", str(ledger_dir),
            "--commitment", commitment_id,
            "--subject", "user-42", "--predicate", "mfa_enabled",
            "--status", "confirmed",
            "--external-ref", "idp-evt-001",
            "--observed-at", "2026-08-12T00:00:00Z",
            "--key-id", "test-key", "--secret", "test-secret",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "recorded: confirmed" in out
    assert "chained to" in out

    store = LedgerStore(ledger_dir)
    try:
        records = list(store.scan())
    finally:
        store.close()
    fulfillments = [r for r in records if (r.capsule.get("chain") or {}).get("parent_capsule_id") == commitment_id]
    assert len(fulfillments) == 1
    assert fulfillments[0].capsule["effect"]["effect_attestation"] == "runtime_claimed"


def test_confirm_ingest_unknown_connector_errors(tmp_path, capsys):
    ledger_dir = tmp_path / "ledger"
    commitment_id = _seed_commitment(ledger_dir)

    rc = main(
        [
            "confirm", "ingest",
            "--ledger", str(ledger_dir),
            "--commitment", commitment_id,
            "--subject", "user-42", "--predicate", "mfa_enabled",
            "--connector", "okta-live",
            "--key-id", "test-key", "--secret", "test-secret",
        ]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "unknown connector" in err


def test_confirm_ingest_missing_signing_key_errors(tmp_path, capsys, monkeypatch):
    for var in (
        "CAPSULE_MCP_SIGNING_KEY_ID", "CAPSULE_MCP_SIGNING_SECRET", ):
        monkeypatch.delenv(var, raising=False)

    ledger_dir = tmp_path / "ledger"
    commitment_id = _seed_commitment(ledger_dir)

    rc = main(
        [
            "confirm", "ingest",
            "--ledger", str(ledger_dir),
            "--commitment", commitment_id,
            "--subject", "user-42", "--predicate", "mfa_enabled",
        ]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "--key-id/--secret are required" in err
