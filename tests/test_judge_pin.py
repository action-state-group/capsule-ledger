# SPDX-License-Identifier: Apache-2.0
"""Tests for the judge pin (design §6c item 1): the ``judge_pin`` block every
``judge_judgment`` capsule now carries -- identity (``judge_pin_digest``),
model id + version, sampling params, prompt digest, adjudication sampling
rate, measured agreement rate -- and the typed ``ExternalProofRef`` slot.
"""
from __future__ import annotations

import pytest

from capsule_ledger.judge.capsules import ExternalProofRef, build_judgment_capsule, judge_pin_digest
from capsule_ledger.judge.errors import (
    EXTERNAL_PROOF_REF_MALFORMED,
    RATE_OUT_OF_RANGE,
    SAMPLING_PARAM_NOT_DIGEST_SAFE,
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
    kwargs = dict(label="agreement_reached", confidence=0.8, model_id="static/v1")
    kwargs.update(overrides)
    return ScoreResult(**kwargs)


def _build(signer, **overrides):
    kwargs = dict(prompt=PROMPT, evidence=_evidence(), result=_result(), operator=OPERATOR, developer=DEVELOPER, signer=signer)
    kwargs.update(overrides)
    return build_judgment_capsule(**kwargs)


# -- full pin shape -----------------------------------------------------------


def test_judgment_carries_full_judge_pin(signer, store):
    result = _result(model_version="v2026-08-01", sampling_params={"temperature_micros": 700_000, "seed": 7})
    capsule = _build(signer, result=result, adjudication_sampling_rate=0.25, measured_agreement_rate=0.9)
    record = store.append(capsule, consequential=False)
    assert store.verify(record.capsule_id).ok

    pin = capsule["asg_payload"]["detail"]["judge_pin"]
    assert pin["model_id"] == "static/v1"
    assert pin["model_version"] == "v2026-08-01"
    assert pin["sampling_params"] == {"temperature_micros": 700_000, "seed": 7}
    assert pin["prompt_digest"] == PROMPT.prompt_digest()
    assert pin["adjudication_sampling_rate_micros"] == 250_000
    assert pin["measured_agreement_rate_micros"] == 900_000
    assert pin["judge_pin_digest"] == judge_pin_digest(
        model_id="static/v1", model_version="v2026-08-01",
        sampling_params={"temperature_micros": 700_000, "seed": 7}, prompt_digest=PROMPT.prompt_digest(),
    )


def test_judge_pin_omits_optional_fields_when_absent(signer):
    capsule = _build(signer)
    pin = capsule["asg_payload"]["detail"]["judge_pin"]
    assert set(pin) == {"judge_pin_digest", "model_id", "prompt_digest"}


def test_judge_pin_digest_is_stable_across_measured_stat_changes(signer):
    # Same reproducible call shape, different point-in-time measured/policy
    # fields -- the pin's own identity must not move just because the
    # measured agreement rate was recomputed between two runs of the SAME
    # judge (this is what makes drift detection meaningful).
    c1 = _build(signer, adjudication_sampling_rate=0.1, measured_agreement_rate=0.5)
    c2 = _build(signer, adjudication_sampling_rate=0.9, measured_agreement_rate=0.99)
    assert c1["asg_payload"]["detail"]["judge_pin"]["judge_pin_digest"] == c2["asg_payload"]["detail"]["judge_pin"]["judge_pin_digest"]
    assert c1["capsule_id"] != c2["capsule_id"]  # the sealed capsule itself still differs


def test_judge_pin_digest_changes_when_model_version_changes(signer):
    c1 = _build(signer, result=_result(model_version="v1"))
    c2 = _build(signer, result=_result(model_version="v2"))
    assert (
        c1["asg_payload"]["detail"]["judge_pin"]["judge_pin_digest"]
        != c2["asg_payload"]["detail"]["judge_pin"]["judge_pin_digest"]
    )


def test_judge_pin_digest_changes_when_sampling_params_change(signer):
    c1 = _build(signer, result=_result(sampling_params={"seed": 1}))
    c2 = _build(signer, result=_result(sampling_params={"seed": 2}))
    assert (
        c1["asg_payload"]["detail"]["judge_pin"]["judge_pin_digest"]
        != c2["asg_payload"]["detail"]["judge_pin"]["judge_pin_digest"]
    )


# -- digest-safety on sampling params and rates -------------------------------


def test_sampling_params_rejects_a_raw_float(signer):
    with pytest.raises(JudgeError) as exc_info:
        _build(signer, result=_result(sampling_params={"temperature": 0.7}))
    assert exc_info.value.reason == SAMPLING_PARAM_NOT_DIGEST_SAFE


@pytest.mark.parametrize("bad_rate", [-0.01, 1.01, "0.5", True])
def test_adjudication_sampling_rate_rejects_out_of_range(signer, bad_rate):
    with pytest.raises(JudgeError) as exc_info:
        _build(signer, adjudication_sampling_rate=bad_rate)
    assert exc_info.value.reason == RATE_OUT_OF_RANGE


@pytest.mark.parametrize("bad_rate", [-0.01, 1.01, "0.5", True])
def test_measured_agreement_rate_rejects_out_of_range(signer, bad_rate):
    with pytest.raises(JudgeError) as exc_info:
        _build(signer, measured_agreement_rate=bad_rate)
    assert exc_info.value.reason == RATE_OUT_OF_RANGE


# -- external proof reference slot --------------------------------------------


def test_judgment_carries_external_proof_ref_when_given(signer, store):
    proof = ExternalProofRef(proof_system="zkml", artifact_digest="f" * 64, artifact_locator="https://proofs.example/1")
    capsule = _build(signer, external_proof=proof)
    record = store.append(capsule, consequential=False)
    assert store.verify(record.capsule_id).ok
    assert capsule["asg_payload"]["detail"]["judge_pin"]["external_proof"] == {
        "proof_system": "zkml",
        "artifact_digest": "f" * 64,
        "artifact_locator": "https://proofs.example/1",
    }


def test_external_proof_ref_omits_locator_when_absent(signer):
    proof = ExternalProofRef(proof_system="zkml", artifact_digest="f" * 64)
    capsule = _build(signer, external_proof=proof)
    assert "artifact_locator" not in capsule["asg_payload"]["detail"]["judge_pin"]["external_proof"]


def test_no_external_proof_key_when_not_given(signer):
    capsule = _build(signer)
    assert "external_proof" not in capsule["asg_payload"]["detail"]["judge_pin"]


@pytest.mark.parametrize("bad_kwargs", [{"proof_system": ""}, {"artifact_digest": ""}])
def test_external_proof_ref_rejects_malformed_fields(signer, bad_kwargs):
    kwargs = dict(proof_system="zkml", artifact_digest="f" * 64)
    kwargs.update(bad_kwargs)
    proof = ExternalProofRef(**kwargs)
    with pytest.raises(JudgeError) as exc_info:
        _build(signer, external_proof=proof)
    assert exc_info.value.reason == EXTERNAL_PROOF_REF_MALFORMED
