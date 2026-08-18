# SPDX-License-Identifier: Apache-2.0
"""Tests for the judge harness's three record types: ``judge_judgment``,
``judge_adjudication``, ``judge_prompt_activated`` -- chain relations, the
adjudication honesty check, label-set/confidence/speaker-role validation,
and determinism.
"""
from __future__ import annotations

import pytest

from capsule_ledger.conversation import ConversationSession
from capsule_ledger.judge.capsules import (
    EVENT_ADJUDICATION,
    EVENT_JUDGMENT,
    EVENT_PROMPT_ACTIVATED,
    build_adjudication_capsule,
    build_judge_prompt_activation_capsule,
    build_judgment_capsule,
    find_adjudications_for_judgment,
    find_judgments_for_session,
    find_latest_prompt_activation,
)
from capsule_ledger.judge.errors import (
    ADJUDICATION_LABEL_MISMATCH,
    CONFIDENCE_OUT_OF_RANGE,
    EMPTY_EVIDENCE_RANGE,
    INVALID_SPEAKER_ROLE_TARGET,
    JUDGMENT_NOT_FOUND,
    LABEL_NOT_IN_LABEL_SET,
    JudgeError,
)
from capsule_ledger.judge.prompt import JudgePromptDefinition
from capsule_ledger.judge.scorer import JudgeEvidence, ScoreResult
from capsule_ledger.ledger import ScanQuery
from capsule_ledger.policy.activation import GENESIS_PARENT

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
    kwargs = dict(label="agreement_reached", confidence=0.8, model_id="static/v1")
    kwargs.update(overrides)
    return ScoreResult(**kwargs)


# -- judgment capsule ------------------------------------------------------


def test_judgment_capsule_is_real_and_independently_verifiable(store, signer):
    capsule = build_judgment_capsule(
        prompt=PROMPT, evidence=_evidence(), result=_result(), operator=OPERATOR, developer=DEVELOPER, signer=signer
    )
    record = store.append(capsule, consequential=False)
    result = store.verify(record.capsule_id)
    assert result.ok, result.findings


def test_judgment_capsule_carries_model_prompt_digest_and_evidence_range(signer):
    capsule = build_judgment_capsule(
        prompt=PROMPT, evidence=_evidence(), result=_result(rationale="clear agreement"),
        operator=OPERATOR, developer=DEVELOPER, signer=signer,
    )
    detail = capsule["asg_payload"]["detail"]
    assert capsule["asg_payload"]["event"] == EVENT_JUDGMENT
    assert detail["prompt_id"] == PROMPT.prompt_id
    assert detail["prompt_digest"] == PROMPT.prompt_digest()
    assert detail["model_id"] == "static/v1"
    assert detail["label"] == "agreement_reached"
    assert detail["confidence_micros"] == 800_000
    assert detail["evidence"]["session_id"] == "sess-1"
    assert detail["evidence"]["turn_capsule_ids"] == ["a" * 64, "b" * 64]
    assert "session_digest" not in detail["evidence"]
    # rationale is digested, never stored raw -- the free text never appears anywhere.
    assert "rationale_digest" in detail
    assert "clear agreement" not in str(capsule)


def test_judgment_capsule_carries_session_digest_when_given(signer):
    capsule = build_judgment_capsule(
        prompt=PROMPT, evidence=_evidence(), result=_result(), operator=OPERATOR, developer=DEVELOPER,
        signer=signer, session_digest="c" * 64,
    )
    assert capsule["asg_payload"]["detail"]["evidence"]["session_digest"] == "c" * 64


def test_judgment_capsule_chains_confirms_to_its_parent(signer):
    capsule = build_judgment_capsule(
        prompt=PROMPT, evidence=_evidence(), result=_result(), operator=OPERATOR, developer=DEVELOPER,
        signer=signer, chain_parent="d" * 64,
    )
    assert capsule["chain"] == {"parent_capsule_id": "d" * 64, "relation": "confirms"}
    assert capsule["assurance"]["ledger_mode"] == "chained"


def test_judgment_capsule_standalone_without_chain_parent(signer):
    capsule = build_judgment_capsule(prompt=PROMPT, evidence=_evidence(), result=_result(), operator=OPERATOR, developer=DEVELOPER, signer=signer)
    assert "chain" not in capsule or capsule.get("chain") is None
    assert capsule["assurance"]["ledger_mode"] == "standalone"


def test_judgment_capsule_speaker_role_targeting(signer):
    capsule = build_judgment_capsule(
        prompt=PROMPT, evidence=_evidence(target_speaker_role="assistant"), result=_result(),
        operator=OPERATOR, developer=DEVELOPER, signer=signer,
    )
    assert capsule["asg_payload"]["detail"]["target_speaker_role"] == "assistant"


def test_judgment_capsule_no_speaker_role_key_when_untargeted(signer):
    capsule = build_judgment_capsule(prompt=PROMPT, evidence=_evidence(), result=_result(), operator=OPERATOR, developer=DEVELOPER, signer=signer)
    assert "target_speaker_role" not in capsule["asg_payload"]["detail"]


@pytest.mark.parametrize("bad_role", ["bot", "System", ""])
def test_judgment_capsule_rejects_invalid_speaker_role_target(signer, bad_role):
    with pytest.raises(JudgeError) as exc_info:
        build_judgment_capsule(
            prompt=PROMPT, evidence=_evidence(target_speaker_role=bad_role), result=_result(),
            operator=OPERATOR, developer=DEVELOPER, signer=signer,
        )
    assert exc_info.value.reason == INVALID_SPEAKER_ROLE_TARGET


def test_judgment_capsule_rejects_label_not_in_label_set(signer):
    with pytest.raises(JudgeError) as exc_info:
        build_judgment_capsule(
            prompt=PROMPT, evidence=_evidence(), result=_result(label="escalated"),
            operator=OPERATOR, developer=DEVELOPER, signer=signer,
        )
    assert exc_info.value.reason == LABEL_NOT_IN_LABEL_SET


@pytest.mark.parametrize("bad_confidence", [-0.01, 1.01, True, "0.5"])
def test_judgment_capsule_rejects_confidence_out_of_range(signer, bad_confidence):
    with pytest.raises(JudgeError) as exc_info:
        build_judgment_capsule(
            prompt=PROMPT, evidence=_evidence(), result=_result(confidence=bad_confidence),
            operator=OPERATOR, developer=DEVELOPER, signer=signer,
        )
    assert exc_info.value.reason == CONFIDENCE_OUT_OF_RANGE


def test_judgment_capsule_rejects_empty_evidence_range(signer):
    with pytest.raises(JudgeError) as exc_info:
        build_judgment_capsule(
            prompt=PROMPT, evidence=_evidence(turn_capsule_ids=()), result=_result(),
            operator=OPERATOR, developer=DEVELOPER, signer=signer,
        )
    assert exc_info.value.reason == EMPTY_EVIDENCE_RANGE


def test_judgment_capsule_confidence_scaling_boundaries(signer):
    for confidence, expected_micros in [(0.0, 0), (1.0, 1_000_000), (0.123456, 123456)]:
        capsule = build_judgment_capsule(
            prompt=PROMPT, evidence=_evidence(), result=_result(confidence=confidence),
            operator=OPERATOR, developer=DEVELOPER, signer=signer,
        )
        assert capsule["asg_payload"]["detail"]["confidence_micros"] == expected_micros


def test_judgment_capsule_is_deterministic_given_explicit_inputs(signer):
    kwargs = dict(
        prompt=PROMPT, evidence=_evidence(), result=_result(), operator=OPERATOR, developer=DEVELOPER, signer=signer,
        timestamp="2026-08-12T09:00:00Z", action_id="judge.judgment/sess-1/conversation.agreement_reached/1.0.0",
    )
    c1 = build_judgment_capsule(**kwargs)
    c2 = build_judgment_capsule(**kwargs)
    assert c1 == c2
    assert c1["capsule_id"] == c2["capsule_id"]

    c3 = build_judgment_capsule(**{**kwargs, "result": _result(label="no_agreement")})
    assert c3["capsule_id"] != c1["capsule_id"]


# -- adjudication capsule --------------------------------------------------


def _judgment(signer, **overrides):
    return build_judgment_capsule(
        prompt=PROMPT, evidence=_evidence(), result=_result(), operator=OPERATOR, developer=DEVELOPER, signer=signer, **overrides
    )


def test_adjudication_capsule_is_real_and_independently_verifiable(store, signer):
    judgment = _judgment(signer)
    store.append(judgment, consequential=False)
    adjudication = build_adjudication_capsule(
        judgment=judgment, label="agreement_reached", agrees_with_judge=True,
        operator=OPERATOR, developer=DEVELOPER, signer=signer, rationale="spot-checked, correct",
    )
    record = store.append(adjudication, consequential=False)
    result = store.verify(record.capsule_id)
    assert result.ok, result.findings


def test_adjudication_capsule_is_human_disposed(signer):
    judgment = _judgment(signer)
    adjudication = build_adjudication_capsule(
        judgment=judgment, label="agreement_reached", agrees_with_judge=True,
        operator=OPERATOR, developer=DEVELOPER, signer=signer,
    )
    assert adjudication["disposition"]["human_disposed"] is True
    assert adjudication["disposition"]["approver"] == "human"
    assert adjudication["disposition"]["decision"] == "accept"
    assert adjudication["asg_payload"]["event"] == EVENT_ADJUDICATION


def test_adjudication_capsule_override_records_reject_and_new_label(signer):
    judgment = _judgment(signer)
    adjudication = build_adjudication_capsule(
        judgment=judgment, label="no_agreement", agrees_with_judge=False,
        operator=OPERATOR, developer=DEVELOPER, signer=signer,
    )
    assert adjudication["disposition"]["decision"] == "reject"
    assert adjudication["asg_payload"]["detail"]["label"] == "no_agreement"
    assert adjudication["asg_payload"]["detail"]["agrees_with_judge"] is False


def test_adjudication_capsule_chains_confirms_to_the_judgment(signer):
    judgment = _judgment(signer)
    adjudication = build_adjudication_capsule(
        judgment=judgment, label="agreement_reached", agrees_with_judge=True,
        operator=OPERATOR, developer=DEVELOPER, signer=signer,
    )
    assert adjudication["chain"] == {"parent_capsule_id": judgment["capsule_id"], "relation": "confirms"}
    assert adjudication["asg_payload"]["detail"]["judgment_capsule_id"] == judgment["capsule_id"]


def test_adjudication_honesty_check_rejects_agree_with_mismatched_label(signer):
    judgment = _judgment(signer)  # judge's own label is "agreement_reached"
    with pytest.raises(JudgeError) as exc_info:
        build_adjudication_capsule(
            judgment=judgment, label="no_agreement", agrees_with_judge=True,
            operator=OPERATOR, developer=DEVELOPER, signer=signer,
        )
    assert exc_info.value.reason == ADJUDICATION_LABEL_MISMATCH


def test_adjudication_rejects_a_non_judgment_capsule(signer):
    not_a_judgment = {"capsule_id": "e" * 64, "asg_payload": {"event": "conversation_turn", "detail": {}}}
    with pytest.raises(JudgeError) as exc_info:
        build_adjudication_capsule(
            judgment=not_a_judgment, label="agreement_reached", agrees_with_judge=True,
            operator=OPERATOR, developer=DEVELOPER, signer=signer,
        )
    assert exc_info.value.reason == JUDGMENT_NOT_FOUND


def test_adjudication_capsule_rationale_digested_never_raw(signer):
    judgment = _judgment(signer)
    adjudication = build_adjudication_capsule(
        judgment=judgment, label="agreement_reached", agrees_with_judge=True,
        operator=OPERATOR, developer=DEVELOPER, signer=signer, rationale="a very specific secret rationale",
    )
    assert adjudication["disposition"]["reason_digest"] is not None
    assert "a very specific secret rationale" not in str(adjudication)


def test_adjudication_capsule_no_reason_digest_without_rationale(signer):
    judgment = _judgment(signer)
    adjudication = build_adjudication_capsule(
        judgment=judgment, label="agreement_reached", agrees_with_judge=True,
        operator=OPERATOR, developer=DEVELOPER, signer=signer,
    )
    assert adjudication["disposition"].get("reason_digest") is None


# -- prompt activation ------------------------------------------------------


def test_prompt_activation_capsule_opens_a_new_epoch_from_genesis(signer):
    capsule = build_judge_prompt_activation_capsule(prompt=PROMPT, operator=OPERATOR, developer=DEVELOPER, signer=signer)
    assert capsule["asg_payload"]["event"] == EVENT_PROMPT_ACTIVATED
    assert capsule["chain"] == {"parent_capsule_id": GENESIS_PARENT, "relation": "epoch_opens"}
    detail = capsule["asg_payload"]["detail"]
    assert detail["prompt_id"] == PROMPT.prompt_id
    assert detail["prompt_digest"] == PROMPT.prompt_digest()
    assert detail["label_set"] == list(PROMPT.label_set)


def test_prompt_activation_capsule_chains_to_previous_activation(signer):
    first = build_judge_prompt_activation_capsule(prompt=PROMPT, operator=OPERATOR, developer=DEVELOPER, signer=signer)
    revised = JudgePromptDefinition(prompt_id=PROMPT.prompt_id, label_set=PROMPT.label_set, instructions=PROMPT.instructions + " (revised)")
    second = build_judge_prompt_activation_capsule(
        prompt=revised, operator=OPERATOR, developer=DEVELOPER, signer=signer, previous_activation_capsule_id=first["capsule_id"],
    )
    assert second["chain"] == {"parent_capsule_id": first["capsule_id"], "relation": "epoch_opens"}
    assert second["asg_payload"]["detail"]["prompt_digest"] != first["asg_payload"]["detail"]["prompt_digest"]


def test_find_latest_prompt_activation(store, signer):
    assert find_latest_prompt_activation(store) is None
    first = build_judge_prompt_activation_capsule(prompt=PROMPT, operator=OPERATOR, developer=DEVELOPER, signer=signer)
    r1 = store.append(first, consequential=False)
    assert find_latest_prompt_activation(store).capsule_id == r1.capsule_id

    revised = JudgePromptDefinition(prompt_id=PROMPT.prompt_id, label_set=PROMPT.label_set, instructions=PROMPT.instructions + " v2")
    second = build_judge_prompt_activation_capsule(
        prompt=revised, operator=OPERATOR, developer=DEVELOPER, signer=signer, previous_activation_capsule_id=r1.capsule_id,
    )
    r2 = store.append(second, consequential=False)
    assert find_latest_prompt_activation(store).capsule_id == r2.capsule_id
    assert find_latest_prompt_activation(store, prompt_id="unrelated.prompt/1.0.0") is None


# -- find_* query helpers ----------------------------------------------------


def test_find_judgments_for_session_isolates_sessions(store, signer):
    j1 = _judgment(signer)
    j2 = build_judgment_capsule(
        prompt=PROMPT, evidence=_evidence(session_id="sess-2"), result=_result(),
        operator=OPERATOR, developer=DEVELOPER, signer=signer,
    )
    store.append(j1, consequential=False)
    store.append(j2, consequential=False)

    found = find_judgments_for_session(store, "sess-1")
    assert [r.capsule_id for r in found] == [j1["capsule_id"]]
    assert find_judgments_for_session(store, "sess-3") == []


def test_find_adjudications_for_judgment(store, signer):
    judgment = _judgment(signer)
    store.append(judgment, consequential=False)
    other_judgment = build_judgment_capsule(
        prompt=PROMPT, evidence=_evidence(session_id="sess-2"), result=_result(),
        operator=OPERATOR, developer=DEVELOPER, signer=signer,
    )
    store.append(other_judgment, consequential=False)

    adjudication = build_adjudication_capsule(
        judgment=judgment, label="agreement_reached", agrees_with_judge=True,
        operator=OPERATOR, developer=DEVELOPER, signer=signer,
    )
    store.append(adjudication, consequential=False)

    found = find_adjudications_for_judgment(store, judgment["capsule_id"])
    assert [r.capsule_id for r in found] == [adjudication["capsule_id"]]
    assert find_adjudications_for_judgment(store, other_judgment["capsule_id"]) == []


def test_event_type_and_scan_filter_shape(store, signer):
    judgment = _judgment(signer)
    store.append(judgment, consequential=False)
    adjudication = build_adjudication_capsule(
        judgment=judgment, label="agreement_reached", agrees_with_judge=True,
        operator=OPERATOR, developer=DEVELOPER, signer=signer,
    )
    store.append(adjudication, consequential=False)

    fyi_records = list(store.scan(ScanQuery(action_type="fyi")))
    events = [r.capsule["asg_payload"]["event"] for r in fyi_records]
    assert events.count(EVENT_JUDGMENT) == 1
    assert events.count(EVENT_ADJUDICATION) == 1


# -- integrates with the real B5 conversation profile ------------------------


def test_judgment_evidence_range_is_real_turn_capsule_ids(store, signer):
    sess = ConversationSession(ledger=store, session_id="sess-real", operator=OPERATOR, developer=DEVELOPER, signer_provider=lambda: signer)
    t0 = sess.record_turn(speaker_role="user", content_digest="a" * 64)
    t1 = sess.record_turn(speaker_role="assistant", content_digest="b" * 64)
    close = sess.close()

    evidence = JudgeEvidence(session_id="sess-real", turn_capsule_ids=(t0.capsule_id, t1.capsule_id), evidence_text="ev")
    judgment = build_judgment_capsule(
        prompt=PROMPT, evidence=evidence, result=_result(), operator=OPERATOR, developer=DEVELOPER, signer=signer,
        session_digest=close.capsule["asg_payload"]["detail"]["session_digest"], chain_parent=close.capsule_id,
    )
    record = store.append(judgment, consequential=False)
    assert store.verify(record.capsule_id).ok
    detail = judgment["asg_payload"]["detail"]
    assert detail["evidence"]["turn_capsule_ids"] == [t0.capsule_id, t1.capsule_id]
    assert detail["evidence"]["session_digest"] == close.capsule["asg_payload"]["detail"]["session_digest"]
    assert judgment["chain"]["parent_capsule_id"] == close.capsule_id
