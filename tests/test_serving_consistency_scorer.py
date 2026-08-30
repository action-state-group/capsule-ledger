# SPDX-License-Identifier: Apache-2.0
"""Tests for the serving/hardware-consistency scorer riding the existing
judge harness.

Net-new code under test is ONLY ``judge/scorers/serving_consistency.py``:
the verdict-sealing, judgment-capsule, and drift-check paths are the
EXISTING harness/capsules, exercised here unmodified. Real capsules are
built via the existing ``conversation.exchange`` builder so the serving
fields under test are the ones a real mesh/tau2 emitter produces.
"""
from __future__ import annotations

import pytest
from agent_action_capsule import compute_capsule_id, json_digest

from capsule_ledger.conversation.exchange import build_conversation_exchange_capsule
from capsule_ledger.judge import JudgeEvidence, JudgeHarness, JudgePromptDefinition
from capsule_ledger.judge.capsules import EVENT_DRIFT_CHECK, EVENT_JUDGMENT
from capsule_ledger.judge.errors import JudgeError
from capsule_ledger.judge.scorers.serving_consistency import (
    LABEL_ABSENT,
    LABEL_CHANGED,
    LABEL_CONSISTENT,
    ServingConsistencyScorer,
    extract_serving_view,
    score_serving_range,
    serving_evidence_text,
)

OPERATOR = "relying-party"
DEVELOPER = "serving-consistency@v1"

PROMPT = JudgePromptDefinition(
    prompt_id="serving.hardware_consistency/1.0.0",
    label_set=(LABEL_CONSISTENT, LABEL_CHANGED, LABEL_ABSENT),
    instructions="Is the serving hardware invariant across the range?",
)


def _capsule(signer, *, node_id, gpu, model_id="llama-3-70b", quant="q4", exchange="e", with_serving=True):
    """A real serving capsule via the existing exchange builder, with the mesh
    serving_provenance keys folded into compute_attestation and re-signed."""
    cap = build_conversation_exchange_capsule(
        session_id=node_id,
        exchange_id=exchange,
        messages=[{"role": "user", "content": "ping"}, {"role": "assistant", "content": "pong"}],
        model_id=model_id,
        provider="mesh",
        operator=OPERATOR,
        developer=DEVELOPER,
        signer=signer,
        quant=quant,
        hardware=gpu,
    )
    if with_serving:
        ca = cap["model_attestation"]["compute_attestation"]
        ca["served_by_node_id"] = node_id
        ca["gpu"] = gpu
        body = {k: v for k, v in cap.items() if k not in ("capsule_id", "asg_signature")}
        body["asg_signature"] = {"key_id": signer.key_id, "alg": signer.algorithm, "sig": signer.sign(json_digest(body))}
        body["capsule_id"] = compute_capsule_id(body)
        return body
    return cap


def _evidence(capsules, node_id="node-alpha"):
    return JudgeEvidence(
        session_id=node_id,
        turn_capsule_ids=tuple(c["capsule_id"] for c in capsules),
        evidence_text=serving_evidence_text(capsules),
    )


def _harness(store, signer):
    return JudgeHarness(
        ledger=store,
        prompt=PROMPT,
        scorer=ServingConsistencyScorer(),
        operator=OPERATOR,
        developer=DEVELOPER,
        signer_provider=lambda: signer,
    )


# --- pure comparison (no harness) -------------------------------------------


def test_consistent_range_scores_consistent(signer):
    caps = [_capsule(signer, node_id="node-alpha", gpu="a100", exchange=str(i)) for i in range(3)]
    verdict = score_serving_range([extract_serving_view(c) for c in caps])
    assert verdict.label == LABEL_CONSISTENT
    assert verdict.flagged_hardware == ()


def test_changed_gpu_is_flagged_hardware(signer):
    caps = [
        _capsule(signer, node_id="node-alpha", gpu="a100", exchange="0"),
        _capsule(signer, node_id="node-alpha", gpu="apple-m3", exchange="1"),
    ]
    verdict = score_serving_range([extract_serving_view(c) for c in caps])
    assert verdict.label == LABEL_CHANGED
    assert "gpu" in verdict.flagged_hardware
    assert "hardware" in verdict.flagged_hardware  # exchange builder's hardware field also moved


def test_changed_node_id_is_flagged_hardware(signer):
    caps = [
        _capsule(signer, node_id="node-alpha", gpu="a100", exchange="0"),
        _capsule(signer, node_id="node-BETA", gpu="a100", exchange="1"),
    ]
    verdict = score_serving_range([extract_serving_view(c) for c in caps])
    assert verdict.label == LABEL_CHANGED
    assert "served_by_node_id" in verdict.flagged_hardware


def test_model_change_is_disclosed_delta_not_hardware_flag(signer):
    caps = [
        _capsule(signer, node_id="node-alpha", gpu="a100", model_id="llama-3-70b", exchange="0"),
        _capsule(signer, node_id="node-alpha", gpu="a100", model_id="llama-3.1-70b", exchange="1"),
    ]
    verdict = score_serving_range([extract_serving_view(c) for c in caps])
    assert verdict.label == LABEL_CHANGED
    assert verdict.flagged_hardware == ()  # same box, disclosed model swap
    assert "model_id" in verdict.changed_model


def test_absent_field_is_absent_never_false_consistent(signer):
    # Capsules with NO serving_provenance keys at all -> absent, not consistent.
    # The exchange builder always writes `hardware`, so a real capsule is never
    # fully field-less; pass genuinely empty views to prove absence is honest.
    empty = score_serving_range([{}, {}])
    assert empty.label == LABEL_ABSENT
    for fc in empty.fields:
        assert fc.state == LABEL_ABSENT
    # And a field present in only some capsules is 'partial', never a clean pass.
    partial = score_serving_range([{"gpu": "a100"}, {}])
    gpu_fc = next(f for f in partial.fields if f.field == "gpu")
    assert gpu_fc.partial is True
    assert gpu_fc.state == LABEL_CONSISTENT  # one distinct value seen, but flagged partial


def test_deterministic_same_range_same_result(signer):
    caps = [_capsule(signer, node_id="node-alpha", gpu="a100", exchange=str(i)) for i in range(3)]
    v1 = score_serving_range([extract_serving_view(c) for c in caps])
    v2 = score_serving_range([extract_serving_view(c) for c in caps])
    assert v1.to_detail() == v2.to_detail()


def test_evidence_text_is_canonical_and_stable(signer):
    caps = [_capsule(signer, node_id="node-alpha", gpu="a100", exchange=str(i)) for i in range(2)]
    assert serving_evidence_text(caps) == serving_evidence_text(caps)


# --- through the EXISTING harness (verdict sealed as a capsule) --------------


def test_wrong_label_set_rejected(store, signer):
    bad_prompt = JudgePromptDefinition(
        prompt_id="serving.hardware_consistency/1.0.0",
        label_set=("yes", "no"),
        instructions="x",
    )
    scorer = ServingConsistencyScorer()
    caps = [_capsule(signer, node_id="node-alpha", gpu="a100", exchange=str(i)) for i in range(2)]
    with pytest.raises(JudgeError):
        scorer.score(evidence=_evidence(caps), prompt=bad_prompt)


def test_harness_seals_consistent_verdict_as_verifiable_capsule(store, signer):
    caps = [_capsule(signer, node_id="node-alpha", gpu="a100", exchange=str(i)) for i in range(3)]
    for c in caps:
        store.append(c, consequential=False)
    harness = _harness(store, signer)
    verdict = harness.run(evidence=_evidence(caps))
    assert store.verify(verdict.capsule_id).ok
    assert verdict.capsule["asg_payload"]["event"] == EVENT_JUDGMENT
    assert verdict.capsule["asg_payload"]["detail"]["label"] == LABEL_CONSISTENT


def test_harness_seals_hardware_flag_verdict_as_verifiable_capsule(store, signer):
    caps = [
        _capsule(signer, node_id="node-alpha", gpu="a100", exchange="0"),
        _capsule(signer, node_id="node-alpha", gpu="a100", exchange="1"),
        _capsule(signer, node_id="node-BETA", gpu="apple-m3", exchange="2"),
    ]
    for c in caps:
        store.append(c, consequential=False)
    harness = _harness(store, signer)
    verdict = harness.run(evidence=_evidence(caps))
    assert store.verify(verdict.capsule_id).ok
    assert verdict.capsule["asg_payload"]["detail"]["label"] == LABEL_CHANGED
    # rationale (which names the flagged hardware) is digested onto the capsule.
    assert verdict.capsule["asg_payload"]["detail"].get("rationale_digest") is not None


def test_drift_check_seals_over_same_range(store, signer):
    caps = [
        _capsule(signer, node_id="node-alpha", gpu="a100", exchange="0"),
        _capsule(signer, node_id="node-BETA", gpu="apple-m3", exchange="1"),
    ]
    for c in caps:
        store.append(c, consequential=False)
    harness = _harness(store, signer)
    evidence = _evidence(caps)
    verdict = harness.run(evidence=evidence)
    drift = harness.check_drift(judgment=verdict.capsule, evidence=evidence)
    assert store.verify(drift.capsule_id).ok
    assert drift.capsule["asg_payload"]["event"] == EVENT_DRIFT_CHECK
    # Deterministic scorer over the SAME range -> no drift.
    assert drift.capsule["asg_payload"]["detail"]["drifted"] is False
    assert drift.capsule["chain"]["parent_capsule_id"] == verdict.capsule_id


def test_full_request_flow_demo_runs(tmp_path):
    from capsule_ledger.examples.serving_consistency_demo import run_flow

    out = run_flow(tmp_path / "demo-ledger")
    assert out["consistent_verdict"] == LABEL_CONSISTENT
    assert out["flagged_verdict"] == LABEL_CHANGED
    assert out["consistent_verifies"] and out["flagged_verifies"] and out["drift_verifies"]
    assert out["drift_flag"] is False
