# SPDX-License-Identifier: Apache-2.0
"""The per-session insufficient_evidence rollup (design §11/§8.4): a
session with an applicable insufficient_evidence term lands in a THIRD
list, "unprovable" -- separate from near-miss (a real failed term)."""
from __future__ import annotations

from capsule_ledger.compiler.session_rollup import rollup_unprovable_sessions
from capsule_ledger.guards import LocalSigner
from capsule_ledger.guards.capsule import build_event_capsule
from capsule_ledger.judge.evidence_completeness import INSUFFICIENT_EVIDENCE

OPERATOR = "test-operator"
DEVELOPER = "test-developer@v1"

_signer = LocalSigner(key_id="session-rollup-test-key", secret=b"session-rollup-test-secret")


def _verdict(*, sim_id: str, term_id: str, verdict: str, missing_evidence: str | None = None, applicable: bool = True):
    detail = {
        "subject": {"sim_id": sim_id},
        "term": {"term_id": term_id, "c_digest": "c" * 64},
        "epoch": "epoch-a",
        "applicable": applicable,
        "verdict": verdict,
        "missing_evidence": missing_evidence,
    }
    return build_event_capsule(operator=OPERATOR, developer=DEVELOPER, signer=_signer, event="judge_agent_verdict", detail=detail)


def test_session_with_only_passing_verdicts_is_absent_from_the_rollup():
    records = [_verdict(sim_id="s1", term_id="term.a", verdict="pass")]
    assert rollup_unprovable_sessions(records) == ()


def test_session_with_an_applicable_insufficient_evidence_term_is_unprovable():
    records = [
        _verdict(sim_id="s1", term_id="term.a", verdict="pass"),
        _verdict(sim_id="s1", term_id="term.b", verdict=INSUFFICIENT_EVIDENCE, missing_evidence="read_observation.chain_parent_digest"),
    ]
    rows = rollup_unprovable_sessions(records)
    assert len(rows) == 1
    row = rows[0]
    assert row.subject == {"sim_id": "s1"}
    assert row.status == "unprovable"
    assert row.failed_terms == ()
    assert len(row.unprovable_terms) == 1
    assert row.unprovable_terms[0].term_id == "term.b"
    assert row.unprovable_terms[0].missing_evidence == "read_observation.chain_parent_digest"


def test_session_with_a_real_failure_is_near_miss_never_rendered_as_unprovable():
    records = [_verdict(sim_id="s1", term_id="term.a", verdict="fail")]
    rows = rollup_unprovable_sessions(records)
    assert len(rows) == 1
    assert rows[0].status == "near_miss"
    assert rows[0].failed_terms[0].term_id == "term.a"
    assert rows[0].unprovable_terms == ()


def test_a_real_failure_and_an_unrelated_insufficient_evidence_term_is_near_miss_not_unprovable():
    records = [
        _verdict(sim_id="s1", term_id="term.a", verdict="fail"),
        _verdict(sim_id="s1", term_id="term.b", verdict=INSUFFICIENT_EVIDENCE, missing_evidence="the missing field"),
    ]
    rows = rollup_unprovable_sessions(records)
    assert len(rows) == 1
    row = rows[0]
    # near-miss (a real failure) is the more actionable finding -- design §11's
    # "separate from near-miss" reads as near-miss taking precedence, not blending.
    assert row.status == "near_miss"
    # but the unprovable term is not discarded -- it's still visible on the row
    assert len(row.unprovable_terms) == 1


def test_inapplicable_insufficient_evidence_rows_never_count_toward_the_rollup():
    records = [_verdict(sim_id="s1", term_id="term.a", verdict=INSUFFICIENT_EVIDENCE, missing_evidence="x", applicable=False)]
    assert rollup_unprovable_sessions(records) == ()


def test_two_sessions_are_grouped_independently_never_blended():
    records = [
        _verdict(sim_id="s1", term_id="term.a", verdict="fail"),
        _verdict(sim_id="s2", term_id="term.a", verdict=INSUFFICIENT_EVIDENCE, missing_evidence="y"),
    ]
    rows = rollup_unprovable_sessions(records)
    by_subject = {row.subject["sim_id"]: row for row in rows}
    assert by_subject["s1"].status == "near_miss"
    assert by_subject["s2"].status == "unprovable"
