# SPDX-License-Identifier: Apache-2.0
"""Tests for the calibration harness seam (design §6c item 4):
``compute_judge_calibration_stats`` folds a ledger's own judgment/
adjudication/drift-check history into plain, re-derivable measured stats,
keyed by ``judge_pin_digest``.
"""
from __future__ import annotations

from capsule_ledger.judge.calibration import compute_judge_calibration_stats
from capsule_ledger.judge.capsules import (
    build_adjudication_capsule,
    build_judge_drift_check_capsule,
    build_judgment_capsule,
    judge_pin_digest,
)
from capsule_ledger.judge.prompt import JudgePromptDefinition
from capsule_ledger.judge.scorer import JudgeEvidence, ScoreResult

OPERATOR = "acme-support"
DEVELOPER = "judge-harness@v1"

PROMPT = JudgePromptDefinition(
    prompt_id="conversation.agreement_reached/1.0.0",
    label_set=("agreement_reached", "no_agreement"),
    instructions="Did the conversation reach agreement on a remedial action?",
)

PIN_DIGEST = judge_pin_digest(model_id="static/v1", model_version=None, sampling_params=None, prompt_digest=PROMPT.prompt_digest())


def _evidence(session_id="sess-1"):
    return JudgeEvidence(session_id=session_id, turn_capsule_ids=("a" * 64,), evidence_text="ev")


def _judgment(signer, session_id="sess-1", label="agreement_reached"):
    result = ScoreResult(label=label, confidence=0.8, model_id="static/v1")
    return build_judgment_capsule(
        prompt=PROMPT, evidence=_evidence(session_id), result=result, operator=OPERATOR, developer=DEVELOPER, signer=signer,
    )


def test_no_judgments_yet_is_all_unmeasured(store):
    stats = compute_judge_calibration_stats(store, PIN_DIGEST)
    assert stats.judgment_count == 0
    assert stats.agreement_rate is None
    assert stats.drift_rate is None


def test_unadjudicated_judgments_leave_agreement_rate_unmeasured(signer, store):
    store.append(_judgment(signer), consequential=False)
    store.append(_judgment(signer, session_id="sess-2"), consequential=False)
    stats = compute_judge_calibration_stats(store, PIN_DIGEST)
    assert stats.judgment_count == 2
    assert stats.adjudicated_count == 0
    assert stats.agreement_rate is None  # unmeasured, never a fabricated 0%


def test_agreement_rate_measured_from_real_adjudications(signer, store):
    j1 = _judgment(signer, session_id="sess-1")
    j2 = _judgment(signer, session_id="sess-2")
    store.append(j1, consequential=False)
    store.append(j2, consequential=False)

    store.append(
        build_adjudication_capsule(
            judgment=j1, label="agreement_reached", agrees_with_judge=True,
            operator=OPERATOR, developer=DEVELOPER, signer=signer,
        ),
        consequential=False,
    )
    store.append(
        build_adjudication_capsule(
            judgment=j2, label="no_agreement", agrees_with_judge=False,
            operator=OPERATOR, developer=DEVELOPER, signer=signer,
        ),
        consequential=False,
    )

    stats = compute_judge_calibration_stats(store, PIN_DIGEST)
    assert stats.judgment_count == 2
    assert stats.adjudicated_count == 2
    assert stats.agreement_count == 1
    assert stats.agreement_rate == 0.5


def test_drift_rate_measured_from_real_drift_checks(signer, store):
    j1 = _judgment(signer, session_id="sess-1")
    store.append(j1, consequential=False)

    matching = build_judge_drift_check_capsule(
        judgment=j1, rerun_prompt=PROMPT, rerun_result=ScoreResult(label="agreement_reached", confidence=0.8, model_id="static/v1"),
        operator=OPERATOR, developer=DEVELOPER, signer=signer,
    )
    drifted = build_judge_drift_check_capsule(
        judgment=j1, rerun_prompt=PROMPT, rerun_result=ScoreResult(label="no_agreement", confidence=0.8, model_id="static/v1"),
        operator=OPERATOR, developer=DEVELOPER, signer=signer, action_id="judge.drift_check/j1/second",
    )
    store.append(matching, consequential=False)
    store.append(drifted, consequential=False)

    stats = compute_judge_calibration_stats(store, PIN_DIGEST)
    assert stats.drift_check_count == 2
    assert stats.drift_count == 1
    assert stats.drift_rate == 0.5


def test_stats_are_scoped_to_one_judge_pin_digest(signer, store):
    store.append(_judgment(signer), consequential=False)
    other_pin = judge_pin_digest(model_id="static/v2", model_version=None, sampling_params=None, prompt_digest=PROMPT.prompt_digest())
    stats = compute_judge_calibration_stats(store, other_pin)
    assert stats.judgment_count == 0


def test_stats_are_re_derivable_deterministically(signer, store):
    j1 = _judgment(signer)
    store.append(j1, consequential=False)
    store.append(
        build_adjudication_capsule(
            judgment=j1, label="agreement_reached", agrees_with_judge=True, operator=OPERATOR, developer=DEVELOPER, signer=signer,
        ),
        consequential=False,
    )
    first = compute_judge_calibration_stats(store, PIN_DIGEST)
    second = compute_judge_calibration_stats(store, PIN_DIGEST)
    assert first == second
