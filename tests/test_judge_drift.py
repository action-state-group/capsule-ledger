# SPDX-License-Identifier: Apache-2.0
"""Tests for the judge drift check (design §6c item 2): re-run a pinned
judge over its own cited evidence and seal match-or-delta -- never a silent
disagreement. This is the acceptance surface for
``[ldg-cs-p5-tower-judge-pin]``: "re-run the existing adversarial-delta pass
against full-pin capsules... a deliberately drifted judge must produce a
sealed delta, not a silent disagreement -- show the drifted case and what it
sealed."
"""
from __future__ import annotations

import pytest

from capsule_ledger.judge.capsules import (
    EVENT_DRIFT_CHECK,
    EVENT_JUDGMENT,
    build_judge_drift_check_capsule,
    build_judgment_capsule,
    find_drift_checks_for_judgment,
)
from capsule_ledger.judge.errors import (
    JUDGE_PIN_MISSING,
    JUDGMENT_NOT_FOUND,
    LABEL_NOT_IN_LABEL_SET,
    JudgeError,
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


def _evidence(**overrides):
    kwargs = dict(session_id="sess-1", turn_capsule_ids=("a" * 64, "b" * 64), evidence_text="the evidence")
    kwargs.update(overrides)
    return JudgeEvidence(**kwargs)


def _result(**overrides):
    kwargs = dict(label="agreement_reached", confidence=0.8, model_id="static/v1", model_version="v1")
    kwargs.update(overrides)
    return ScoreResult(**kwargs)


def _judgment(signer, **overrides):
    kwargs = dict(prompt=PROMPT, evidence=_evidence(), result=_result(), operator=OPERATOR, developer=DEVELOPER, signer=signer)
    kwargs.update(overrides)
    return build_judgment_capsule(**kwargs)


def _drift_check(signer, judgment, **overrides):
    kwargs = dict(
        judgment=judgment, rerun_prompt=PROMPT, rerun_result=_result(),
        operator=OPERATOR, developer=DEVELOPER, signer=signer,
    )
    kwargs.update(overrides)
    return build_judge_drift_check_capsule(**kwargs)


# -- the acceptance case: a deliberately drifted judge seals a real delta ----


def test_deliberately_drifted_judge_seals_a_delta_not_a_silent_disagreement(signer, store):
    judgment = _judgment(signer)
    store.append(judgment, consequential=False)

    # Deliberately drift the judge: the SAME pin (model/version/params/prompt
    # unchanged) now returns the OTHER label -- a real disagreement.
    drifted_result = _result(label="no_agreement")
    capsule = build_judge_drift_check_capsule(
        judgment=judgment, rerun_prompt=PROMPT, rerun_result=drifted_result,
        operator=OPERATOR, developer=DEVELOPER, signer=signer,
    )
    record = store.append(capsule, consequential=False)

    # It is SEALED: real, chained, independently verifiable -- not a
    # transient return value the caller could silently drop.
    verify_result = store.verify(record.capsule_id)
    assert verify_result.ok, verify_result.findings
    assert capsule["asg_payload"]["event"] == EVENT_DRIFT_CHECK
    assert capsule["chain"] == {"parent_capsule_id": judgment["capsule_id"], "relation": "confirms"}

    detail = capsule["asg_payload"]["detail"]
    # The delta itself is shown, not just a boolean: both labels are on the
    # sealed record, so "what it sealed" is answerable from the ledger alone.
    assert detail["drifted"] is True
    assert detail["label_matches"] is False
    assert detail["pin_matches"] is True  # same judge -- it really did disagree with itself
    assert detail["original_label"] == "agreement_reached"
    assert detail["rerun_label"] == "no_agreement"
    assert detail["judgment_capsule_id"] == judgment["capsule_id"]

    # It shows up on a query of this judgment's drift checks -- discoverable,
    # not silent.
    found = find_drift_checks_for_judgment(store, judgment["capsule_id"])
    assert [r.capsule_id for r in found] == [record.capsule_id]


def test_matching_rerun_seals_a_no_drift_record(signer, store):
    judgment = _judgment(signer)
    store.append(judgment, consequential=False)
    capsule = _drift_check(signer, judgment)  # identical result -- no drift
    record = store.append(capsule, consequential=False)
    assert store.verify(record.capsule_id).ok

    detail = capsule["asg_payload"]["detail"]
    assert detail["drifted"] is False
    assert detail["pin_matches"] is True
    assert detail["label_matches"] is True


def test_pin_mismatch_alone_counts_as_drift_even_with_the_same_label(signer, store):
    # A silent model upgrade: same label, but it isn't even the same judge
    # configuration anymore -- that is drift too, not a clean match.
    judgment = _judgment(signer, result=_result(model_version="v1"))
    store.append(judgment, consequential=False)
    capsule = _drift_check(signer, judgment, rerun_result=_result(model_version="v2"))
    detail = capsule["asg_payload"]["detail"]
    assert detail["pin_matches"] is False
    assert detail["label_matches"] is True
    assert detail["drifted"] is True


# -- validation ----------------------------------------------------------------


def test_drift_check_rejects_a_non_judgment_capsule(signer):
    not_a_judgment = {"capsule_id": "e" * 64, "asg_payload": {"event": "conversation_turn", "detail": {}}}
    with pytest.raises(JudgeError) as exc_info:
        build_judge_drift_check_capsule(
            judgment=not_a_judgment, rerun_prompt=PROMPT, rerun_result=_result(),
            operator=OPERATOR, developer=DEVELOPER, signer=signer,
        )
    assert exc_info.value.reason == JUDGMENT_NOT_FOUND


def test_drift_check_rejects_a_judgment_with_no_judge_pin(signer):
    # A pre-full-pin judgment (the old model_id + prompt_digest -only shape)
    # has no reproducible identity to check drift against.
    bare_judgment = {
        "capsule_id": "d" * 64,
        "asg_payload": {"event": EVENT_JUDGMENT, "detail": {"model_id": "static/v1", "prompt_digest": "x", "label": "agreement_reached"}},
    }
    with pytest.raises(JudgeError) as exc_info:
        build_judge_drift_check_capsule(
            judgment=bare_judgment, rerun_prompt=PROMPT, rerun_result=_result(),
            operator=OPERATOR, developer=DEVELOPER, signer=signer,
        )
    assert exc_info.value.reason == JUDGE_PIN_MISSING


def test_drift_check_rejects_rerun_label_not_in_label_set(signer):
    judgment = _judgment(signer)
    with pytest.raises(JudgeError) as exc_info:
        build_judge_drift_check_capsule(
            judgment=judgment, rerun_prompt=PROMPT, rerun_result=_result(label="escalated"),
            operator=OPERATOR, developer=DEVELOPER, signer=signer,
        )
    assert exc_info.value.reason == LABEL_NOT_IN_LABEL_SET


def test_find_drift_checks_for_judgment_isolates_by_judgment(signer, store):
    j1 = _judgment(signer)
    j2 = _judgment(signer, evidence=_evidence(session_id="sess-2"))
    store.append(j1, consequential=False)
    store.append(j2, consequential=False)

    d1 = _drift_check(signer, j1)
    store.append(d1, consequential=False)

    assert [r.capsule_id for r in find_drift_checks_for_judgment(store, j1["capsule_id"])] == [d1["capsule_id"]]
    assert find_drift_checks_for_judgment(store, j2["capsule_id"]) == []
