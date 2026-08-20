# SPDX-License-Identifier: Apache-2.0
"""Precondition vocabulary v0 (design §2.4, build plan Phase 2 item 4):
closed six-primitive set, two-sided conformance vectors, verified at
registration."""
from __future__ import annotations

import pytest

from capsule_ledger.compiler.precondition import (
    CONFORMANCE_VECTORS,
    PRECONDITION_KINDS,
    ConformanceVector,
    EvidenceRecord,
    InvalidPreconditionParams,
    PreconditionPrimitive,
    check_backward,
    check_forward,
    verify_conformance_vectors,
)
from capsule_ledger.guards.plan import PlanPrecondition


def test_precondition_kinds_is_the_closed_v0_set():
    assert PRECONDITION_KINDS == {
        "cite_record_of_kind",
        "human_approval_of_grade",
        "cap",
        "within_window_of_record",
        "step_order",
        "dedupe_key",
    }


def test_unknown_kind_is_rejected():
    with pytest.raises(InvalidPreconditionParams, match="kind"):
        PreconditionPrimitive(kind="not_a_real_primitive", params={})


@pytest.mark.parametrize(
    "kind,params",
    [
        ("cite_record_of_kind", {}),
        ("human_approval_of_grade", {"grade": "Z"}),  # not on the ladder
        ("cap", {"limit_minor": -1}),
        ("cap", {"limit_minor": 1.5}),
        ("within_window_of_record", {"duration": "not-a-duration", "reference_kind": "x"}),
        ("step_order", {}),
        ("dedupe_key", {}),
    ],
)
def test_invalid_params_are_rejected_per_kind(kind, params):
    with pytest.raises(InvalidPreconditionParams):
        PreconditionPrimitive(kind=kind, params=params)


def test_citing_label_is_a_short_slug_not_prose():
    primitive = PreconditionPrimitive(kind="cite_record_of_kind", params={"record_kind": "incident_ticket"})
    label = primitive.citing_label()
    assert label == "cite_record_of_kind:record_kind=incident_ticket"
    assert " " not in label


def test_to_plan_precondition_reuses_existing_plan_containment_machinery():
    primitive = PreconditionPrimitive(kind="cap", params={"limit_minor": 500})
    plan_precondition = primitive.to_plan_precondition(action="dispatch")
    assert isinstance(plan_precondition, PlanPrecondition)
    assert plan_precondition.action == "dispatch"
    assert plan_precondition.citing == primitive.citing_label()


def test_every_conformance_vector_kind_covers_the_full_closed_set():
    assert {v.kind for v in CONFORMANCE_VECTORS} == PRECONDITION_KINDS


def test_every_conformance_vector_has_both_a_pass_and_a_backward_only_failure_scenario():
    for kind in PRECONDITION_KINDS:
        vectors = [v for v in CONFORMANCE_VECTORS if v.kind == kind]
        assert any(v.expect_backward for v in vectors), f"{kind}: no passing backward scenario"
        assert any(not v.expect_backward for v in vectors), f"{kind}: no failing backward scenario"


def test_registered_conformance_vectors_pass_both_directions():
    # This IS the P2 acceptance line: "each precondition primitive's vector
    # pair passes in both directions."
    assert verify_conformance_vectors() == []


def test_import_time_gate_already_ran_clean():
    # ``precondition.py`` calls ``assert_conformance_vectors_hold()`` at
    # import time; if this module imported at all, that already passed.
    import capsule_ledger.compiler.precondition as precondition_module

    assert precondition_module is not None


# --- RED-before-green: verify_conformance_vectors can actually fail --------


def test_verify_conformance_vectors_flags_a_forward_mismatch():
    corrupted = (
        ConformanceVector(
            kind="cite_record_of_kind",
            scenario="deliberately_wrong_forward_expectation",
            forward_citation=EvidenceRecord(kind="incident_ticket"),
            evidence=(EvidenceRecord(kind="incident_ticket"),),
            expect_forward=False,  # real evaluator returns True -- this must be flagged
            expect_backward=True,
        ),
    )
    violations = verify_conformance_vectors(corrupted)
    assert any("forward evaluator returned True" in v for v in violations)


def test_verify_conformance_vectors_flags_a_backward_mismatch():
    corrupted = (
        ConformanceVector(
            kind="cap",
            scenario="deliberately_wrong_backward_expectation",
            forward_citation=EvidenceRecord(kind="spend", amount_minor=100),
            evidence=(EvidenceRecord(kind="spend", amount_minor=999999),),
            expect_forward=True,
            expect_backward=True,  # real evaluator returns False (over the seeded 500 limit) -- must be flagged
        ),
    )
    violations = verify_conformance_vectors(corrupted)
    assert any("backward evaluator returned False" in v for v in violations)


def test_verify_conformance_vectors_flags_a_missing_kind():
    only_one = tuple(v for v in CONFORMANCE_VECTORS if v.kind == "cap")
    violations = verify_conformance_vectors(only_one)
    assert any("no published conformance vector" in v for v in violations)


# --- forward purity: presence-only, never sums/orders/compares --------------


def test_forward_evaluator_cannot_sum_across_records_only_confirm_presence():
    primitive = PreconditionPrimitive(kind="cap", params={"limit_minor": 100})
    # A single citation under the limit passes forward -- forward has no
    # other record to sum against.
    assert check_forward(primitive, EvidenceRecord(kind="spend", amount_minor=50)) is True


def test_forward_evaluator_returns_false_with_no_citation():
    primitive = PreconditionPrimitive(kind="cite_record_of_kind", params={"record_kind": "incident_ticket"})
    assert check_forward(primitive, None) is False


def test_backward_evaluator_sums_across_the_full_sealed_evidence_set():
    primitive = PreconditionPrimitive(kind="cap", params={"limit_minor": 100})
    over_limit = (EvidenceRecord(kind="spend", amount_minor=60), EvidenceRecord(kind="spend", amount_minor=60))
    assert check_backward(primitive, over_limit) is False
    under_limit = (EvidenceRecord(kind="spend", amount_minor=40), EvidenceRecord(kind="spend", amount_minor=40))
    assert check_backward(primitive, under_limit) is True


def test_backward_evaluator_rejects_a_duplicate_dedupe_key():
    primitive = PreconditionPrimitive(kind="dedupe_key", params={"key_field": "order_id"})
    duplicated = (EvidenceRecord(kind="subject", key="order-1"), EvidenceRecord(kind="subject", key="order-1"))
    assert check_backward(primitive, duplicated) is False


def test_backward_evaluator_enforces_step_order():
    primitive = PreconditionPrimitive(kind="step_order", params={"after_kind": "human_approval"})
    wrong_order = (EvidenceRecord(kind="human_approval", step=5), EvidenceRecord(kind="subject", step=1))
    assert check_backward(primitive, wrong_order) is False
    right_order = (EvidenceRecord(kind="human_approval", step=1), EvidenceRecord(kind="subject", step=5))
    assert check_backward(primitive, right_order) is True
