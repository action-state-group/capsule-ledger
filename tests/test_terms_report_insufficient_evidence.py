# SPDX-License-Identifier: Apache-2.0
"""``insufficient_evidence`` (design §11) in the rendered term report:
counted in ``verdict_counts`` like any other verdict value, excluded from
``coverage_n`` the same way ``ABSTAIN`` is (never laundered into "judged"),
and never counted as ``fail`` -- plus the report names the missing
field(s) via ``TermReportLine.insufficient_evidence_fields``."""
from __future__ import annotations

from capsule_ledger.compiler.compile import Declaration
from capsule_ledger.compiler.terms_desk import (
    ApplicabilitySpec,
    JudgeOrRuleSpec,
    TermDeclaration,
    compile_term,
)
from capsule_ledger.compiler.terms_report import INSUFFICIENT_EVIDENCE, render_terms_report
from capsule_ledger.guards import LocalSigner
from capsule_ledger.guards.capsule import build_event_capsule
from capsule_ledger.judge.evidence_completeness import verdict_detail

OPERATOR = "test-operator"
DEVELOPER = "test-developer@v1"

_signer = LocalSigner(key_id="insufficient-evidence-report-test-key", secret=b"insufficient-evidence-report-test-secret")


def _judged_term(term_id: str = "term.judged_care"):
    declaration = Declaration(outcome_id=term_id, statement="the agent acted on what it read", requires_model_judgment=True)
    term = TermDeclaration(
        term_id=term_id,
        statement=declaration.statement,
        clause_ref="contract/§7.1",
        applicability=ApplicabilitySpec(unit="conversation"),
        verdict_schema=("pass", "fail"),
        declaration=declaration,
        judge_spec=JudgeOrRuleSpec(kind="judge", verdict_schema=("pass", "fail"), model_id="judge-model-x@1", prompt_digest="p" * 64),
    )
    return compile_term(term)


def _record(*, term_id: str, c_digest: str, epoch: str, verdict: str, missing_evidence: str | None = None, subject_id: str = "1"):
    detail = verdict_detail(
        subject={"sim_id": subject_id},
        term_id=term_id,
        c_digest=c_digest,
        epoch=epoch,
        applicable=True,
        verdict=verdict,
        missing_evidence=missing_evidence,
    )
    return build_event_capsule(operator=OPERATOR, developer=DEVELOPER, signer=_signer, event="judge_agent_verdict", detail=detail)


def test_insufficient_evidence_is_counted_but_never_as_fail():
    ct = _judged_term()
    c_digest = "1" * 64
    records = [
        _record(term_id=ct.term_id, c_digest=c_digest, epoch="epoch-a", verdict="pass", subject_id="1"),
        _record(term_id=ct.term_id, c_digest=c_digest, epoch="epoch-a", verdict=INSUFFICIENT_EVIDENCE, missing_evidence="read_observation.chain_parent_digest", subject_id="2"),
    ]
    report = render_terms_report((ct,), records)
    line = report.lines[0]
    assert line.verdict_counts == {"pass": 1, INSUFFICIENT_EVIDENCE: 1}
    assert line.verdict_counts.get("fail", 0) == 0


def test_insufficient_evidence_is_excluded_from_coverage_same_as_abstain():
    ct = _judged_term()
    c_digest = "1" * 64
    records = [
        _record(term_id=ct.term_id, c_digest=c_digest, epoch="epoch-a", verdict="pass", subject_id="1"),
        _record(term_id=ct.term_id, c_digest=c_digest, epoch="epoch-a", verdict=INSUFFICIENT_EVIDENCE, missing_evidence="x", subject_id="2"),
        _record(term_id=ct.term_id, c_digest=c_digest, epoch="epoch-a", verdict=INSUFFICIENT_EVIDENCE, missing_evidence="x", subject_id="3"),
    ]
    report = render_terms_report((ct,), records)
    line = report.lines[0]
    assert line.applicable_n == 3
    # 3 applicable minus 2 insufficient_evidence -- never counted as judged coverage
    assert line.coverage_n == 1


def test_report_names_the_missing_field():
    ct = _judged_term()
    c_digest = "1" * 64
    records = [
        _record(term_id=ct.term_id, c_digest=c_digest, epoch="epoch-a", verdict=INSUFFICIENT_EVIDENCE, missing_evidence="read_observation.chain_parent_digest", subject_id="1"),
        _record(term_id=ct.term_id, c_digest=c_digest, epoch="epoch-a", verdict=INSUFFICIENT_EVIDENCE, missing_evidence="read_observation.chain_parent_digest", subject_id="2"),
        _record(term_id=ct.term_id, c_digest=c_digest, epoch="epoch-a", verdict=INSUFFICIENT_EVIDENCE, missing_evidence="other.field", subject_id="3"),
    ]
    report = render_terms_report((ct,), records)
    line = report.lines[0]
    assert line.insufficient_evidence_fields == ("other.field", "read_observation.chain_parent_digest")


def test_a_term_with_no_insufficient_evidence_rows_names_nothing():
    ct = _judged_term()
    c_digest = "1" * 64
    records = [_record(term_id=ct.term_id, c_digest=c_digest, epoch="epoch-a", verdict="pass", subject_id="1")]
    report = render_terms_report((ct,), records)
    assert report.lines[0].insufficient_evidence_fields == ()


def test_to_dict_renders_verdict_counts_coverage_and_missing_fields_together():
    ct = _judged_term()
    c_digest = "1" * 64
    records = [
        _record(term_id=ct.term_id, c_digest=c_digest, epoch="epoch-a", verdict="pass", subject_id="1"),
        _record(term_id=ct.term_id, c_digest=c_digest, epoch="epoch-a", verdict=INSUFFICIENT_EVIDENCE, missing_evidence="the missing field", subject_id="2"),
    ]
    report = render_terms_report((ct,), records)
    d = report.lines[0].to_dict()
    assert d["verdict_counts"] == {"pass": 1, INSUFFICIENT_EVIDENCE: 1}
    assert d["coverage"] == {"n": 1, "m": d["units_in_range"]}
    assert d["insufficient_evidence_fields"] == ["the missing field"]
