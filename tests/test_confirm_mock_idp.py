# SPDX-License-Identifier: Apache-2.0
"""``MockIdPConnector``: deterministic in-memory reference connector."""
from __future__ import annotations

import pytest

from capsule_ledger.confirm.connectors import MockIdPConnector


def test_unset_pair_reports_nothing_observed():
    connector = MockIdPConnector()
    assert connector.read_confirmation(subject="user-42", predicate="mfa_enabled") is None


def test_seeded_pair_is_read_back():
    connector = MockIdPConnector()
    connector.set_state(
        subject="user-42", predicate="mfa_enabled", status="confirmed",
        external_ref="idp-evt-001", observed_at="2026-08-12T00:00:00Z",
    )
    observation = connector.read_confirmation(subject="user-42", predicate="mfa_enabled")
    assert observation is not None
    assert observation.status == "confirmed"
    assert observation.external_ref == "idp-evt-001"
    assert observation.observed_at == "2026-08-12T00:00:00Z"


def test_distinct_pairs_are_independent():
    connector = MockIdPConnector()
    connector.set_state(
        subject="user-42", predicate="mfa_enabled", status="confirmed",
        external_ref="idp-evt-001", observed_at="2026-08-12T00:00:00Z",
    )
    assert connector.read_confirmation(subject="user-99", predicate="mfa_enabled") is None
    assert connector.read_confirmation(subject="user-42", predicate="ticket_resolved") is None


def test_clear_state_reverts_to_unobserved():
    connector = MockIdPConnector()
    connector.set_state(
        subject="user-42", predicate="mfa_enabled", status="confirmed",
        external_ref="idp-evt-001", observed_at="2026-08-12T00:00:00Z",
    )
    connector.clear_state(subject="user-42", predicate="mfa_enabled")
    assert connector.read_confirmation(subject="user-42", predicate="mfa_enabled") is None


def test_invalid_status_rejected():
    connector = MockIdPConnector()
    with pytest.raises(ValueError):
        connector.set_state(
            subject="user-42", predicate="mfa_enabled", status="pending",
            external_ref="idp-evt-001", observed_at="2026-08-12T00:00:00Z",
        )


def test_default_evidence_is_synthesized_when_omitted():
    connector = MockIdPConnector()
    connector.set_state(
        subject="user-42", predicate="mfa_enabled", status="confirmed",
        external_ref="idp-evt-001", observed_at="2026-08-12T00:00:00Z",
    )
    observation = connector.read_confirmation(subject="user-42", predicate="mfa_enabled")
    assert observation.evidence == {"subject": "user-42", "predicate": "mfa_enabled", "status": "confirmed"}
