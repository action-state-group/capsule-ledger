# SPDX-License-Identifier: Apache-2.0
"""Scope census (T2), compilation record C, and refusal capsules -- the
three objects the design calls "very hard to add once history is sealed
without" (design §2.3/§4/§4b gap 3)."""
from __future__ import annotations

import hashlib

import pytest

from capsule_ledger.compiler.compilation_record import (
    EVENT_COMPILATION_RECORD,
    build_compilation_record_capsule,
)
from capsule_ledger.compiler.re_derivability import UnknownCheckType, grade_for_check
from capsule_ledger.compiler.refusal import EVENT_REFUSAL, InvalidLabel, build_refusal_capsule
from capsule_ledger.compiler.scope_census import EVENT_SCOPE_CENSUS, build_scope_census_capsule
from capsule_ledger.compiler.vocabulary import VerdictPair

OPERATOR = "test-operator"
DEVELOPER = "test-developer@v1"


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- scope census ------------------------------------------------------


def test_scope_census_seals_n_of_m(signer):
    cap = build_scope_census_capsule(
        document_digest=_digest("doc"),
        n=23,
        m=88,
        review_by="2027-01-01",
        operator=OPERATOR,
        developer=DEVELOPER,
        signer=signer,
    )
    assert cap["asg_payload"]["event"] == EVENT_SCOPE_CENSUS
    assert cap["asg_payload"]["detail"] == {"document_digest": _digest("doc"), "n": 23, "m": 88, "review_by": "2027-01-01"}


def test_scope_census_rejects_n_greater_than_m(signer):
    with pytest.raises(ValueError, match="must not exceed"):
        build_scope_census_capsule(
            document_digest=_digest("doc"), n=99, m=10, review_by="2027-01-01", operator=OPERATOR, developer=DEVELOPER, signer=signer
        )


def test_scope_census_requires_a_review_by_date(signer):
    with pytest.raises(ValueError, match="review_by"):
        build_scope_census_capsule(
            document_digest=_digest("doc"), n=1, m=1, review_by="", operator=OPERATOR, developer=DEVELOPER, signer=signer
        )


# --- compilation record C ------------------------------------------------


def test_compilation_record_seals_the_full_shape(signer):
    cap = build_compilation_record_capsule(
        d_digest=_digest("D"),
        p_digest=_digest("P"),
        f_digest=_digest("F"),
        compiler_id="asg.compiler",
        compiler_version="0.1.0",
        operator=OPERATOR,
        developer=DEVELOPER,
        signer=signer,
        d_prev_digest=_digest("D_prev"),
        replay_report_digest=_digest("replay"),
    )
    assert cap["asg_payload"]["event"] == EVENT_COMPILATION_RECORD
    detail = cap["asg_payload"]["detail"]
    assert detail["d_digest"] == _digest("D")
    assert detail["p_digest"] == _digest("P")
    assert detail["f_digest"] == _digest("F")
    assert detail["d_prev_digest"] == _digest("D_prev")
    assert detail["replay_report_digest"] == _digest("replay")


def test_compilation_record_omits_lineage_fields_when_this_is_genesis(signer):
    cap = build_compilation_record_capsule(
        d_digest=_digest("D"),
        p_digest=_digest("P"),
        f_digest=_digest("F"),
        compiler_id="asg.compiler",
        compiler_version="0.1.0",
        operator=OPERATOR,
        developer=DEVELOPER,
        signer=signer,
    )
    detail = cap["asg_payload"]["detail"]
    assert "d_prev_digest" not in detail
    assert "replay_report_digest" not in detail


@pytest.mark.parametrize("field", ["d_digest", "p_digest", "f_digest"])
def test_compilation_record_requires_a_real_digest_for_every_required_field(signer, field):
    kwargs = dict(
        d_digest=_digest("D"),
        p_digest=_digest("P"),
        f_digest=_digest("F"),
        compiler_id="asg.compiler",
        compiler_version="0.1.0",
        operator=OPERATOR,
        developer=DEVELOPER,
        signer=signer,
    )
    kwargs[field] = "not-a-digest"
    with pytest.raises(ValueError, match=field):
        build_compilation_record_capsule(**kwargs)


# --- refusal capsule -------------------------------------------------------


def test_refusal_capsule_carries_zero_free_prose(signer):
    cap = build_refusal_capsule(
        verdict=VerdictPair(forward="REFUSED", backward="REFUSED"),
        statement_digest=_digest("statement"),
        reason_code="agent_caused_resolution_undecomposable",
        operator=OPERATOR,
        developer=DEVELOPER,
        signer=signer,
        labelled_item_kind="proxy",
        labelled_item_label="recommendation_acted_on",
    )
    assert cap["asg_payload"]["event"] == EVENT_REFUSAL
    detail = cap["asg_payload"]["detail"]
    assert detail["reason_code"] == "agent_caused_resolution_undecomposable"
    assert detail["labelled_item"] == {"kind": "proxy", "label": "recommendation_acted_on"}


def test_refusal_capsule_rejects_a_verdict_pair_with_neither_side_refused(signer):
    with pytest.raises(ValueError, match="REFUSED"):
        build_refusal_capsule(
            verdict=VerdictPair(forward="DETERMINISTIC", backward="DETERMINISTIC"),
            statement_digest=_digest("statement"),
            reason_code="agent_caused_resolution_undecomposable",
            operator=OPERATOR,
            developer=DEVELOPER,
            signer=signer,
        )


def test_refusal_capsule_rejects_a_prose_label_masquerading_as_a_slug(signer):
    with pytest.raises(InvalidLabel):
        build_refusal_capsule(
            verdict=VerdictPair(forward="REFUSED", backward="REFUSED"),
            statement_digest=_digest("statement"),
            reason_code="agent_caused_resolution_undecomposable",
            operator=OPERATOR,
            developer=DEVELOPER,
            signer=signer,
            labelled_item_kind="instrumentation",
            labelled_item_label="the decline event is not recorded today, someone should add it",
        )


# --- re-derivability grade -------------------------------------------------


def test_grade_for_check_matches_the_design_containment_vs_caps_split():
    assert grade_for_check("plan_containment") == "pure_replay"
    assert grade_for_check("caps") == "ledger_state_dependent"


def test_grade_for_check_raises_for_an_unseeded_check():
    with pytest.raises(UnknownCheckType):
        grade_for_check("some_future_check_nobody_seeded_yet")
