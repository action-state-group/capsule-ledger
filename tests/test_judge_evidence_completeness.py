# SPDX-License-Identifier: Apache-2.0
"""The fourth verdict state (backward-judge design §11): ``insufficient_
evidence`` is a structural gate, not a post-hoc relabelling -- when a
term's required evidence is absent, the real judge/scorer callback must
never run, and the sealed detail must always name the missing field."""
from __future__ import annotations

import pytest

from capsule_ledger.judge.errors import JudgeError
from capsule_ledger.judge.evidence_completeness import (
    INSUFFICIENT_EVIDENCE,
    EvidenceRequirement,
    first_missing_requirement,
    resolve_verdict,
    verdict_detail,
)


def test_first_missing_requirement_is_none_when_everything_present():
    reqs = (EvidenceRequirement(path="a.b"), EvidenceRequirement(path="c"))
    assert first_missing_requirement(reqs, {"a": {"b": 1}, "c": 2}) is None


def test_first_missing_requirement_reports_first_absent_in_declared_order():
    reqs = (EvidenceRequirement(path="a.b"), EvidenceRequirement(path="c"))
    missing = first_missing_requirement(reqs, {"c": 2})  # "a.b" absent, "c" present
    assert missing is not None
    assert missing.path == "a.b"


def test_a_null_value_counts_as_absent_not_present():
    reqs = (EvidenceRequirement(path="read_observation.chain_parent_digest"),)
    missing = first_missing_requirement(reqs, {"read_observation": {"chain_parent_digest": None}})
    assert missing is not None
    assert missing.path == "read_observation.chain_parent_digest"


def test_display_label_defaults_to_path_but_can_be_overridden():
    assert EvidenceRequirement(path="a.b").display_label == "a.b"
    assert EvidenceRequirement(path="a.b", label="the A/B field").display_label == "the A/B field"


def test_resolve_verdict_never_calls_judge_when_evidence_is_missing():
    reqs = (EvidenceRequirement(path="missing_field", label="the missing capsule shape"),)
    calls: list[str] = []

    def judge() -> str:
        calls.append("called")
        return "pass"

    verdict, missing_evidence = resolve_verdict(reqs, {}, judge=judge)
    assert verdict == INSUFFICIENT_EVIDENCE
    assert missing_evidence == "the missing capsule shape"
    assert calls == []  # the judge must never run over incomplete evidence


def test_resolve_verdict_calls_judge_when_evidence_is_complete():
    reqs = (EvidenceRequirement(path="a"),)
    verdict, missing_evidence = resolve_verdict(reqs, {"a": 1}, judge=lambda: "fail")
    assert verdict == "fail"
    assert missing_evidence is None


def test_verdict_detail_requires_missing_evidence_label_when_insufficient():
    with pytest.raises(JudgeError) as exc:
        verdict_detail(
            subject={"sim_id": "1"},
            term_id="term.x",
            c_digest="c" * 64,
            epoch="epoch-a",
            applicable=True,
            verdict=INSUFFICIENT_EVIDENCE,
            missing_evidence=None,
        )
    assert exc.value.reason == "missing_evidence_label_required"


def test_verdict_detail_forbids_missing_evidence_label_on_a_real_verdict():
    with pytest.raises(JudgeError) as exc:
        verdict_detail(
            subject={"sim_id": "1"},
            term_id="term.x",
            c_digest="c" * 64,
            epoch="epoch-a",
            applicable=True,
            verdict="pass",
            missing_evidence="should not be here",
        )
    assert exc.value.reason == "missing_evidence_label_not_allowed"


def test_verdict_detail_shape_names_the_field_and_never_defaults_to_fail_or_pass():
    detail = verdict_detail(
        subject={"sim_id": "1"},
        term_id="term.x",
        c_digest="c" * 64,
        epoch="epoch-a",
        applicable=True,
        verdict=INSUFFICIENT_EVIDENCE,
        missing_evidence="read_observation.chain_parent_digest",
    )
    assert detail["verdict"] == INSUFFICIENT_EVIDENCE
    assert detail["verdict"] not in ("pass", "fail")
    assert detail["missing_evidence"] == "read_observation.chain_parent_digest"
