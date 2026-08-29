# SPDX-License-Identifier: Apache-2.0
"""Walkthrough test for [tau2-engagement-conversation-detail-capsules]:
proves one real tau2 airline simulation's full conversation (message text +
model + flattened tool-call trail) seals into a capsule carrying the SAME
shape ``capsule-emit-mesh``'s ``mesh_record_emitter.py`` uses for its
inference capsules -- ``model_attestation.compute_attestation`` with
``agent_input_digest``/``agent_output_digest`` plus the labeled
``reasoning_digest``/``tool_calls_digest`` sub-digests (CPB
``mesh-inference-exchange`` registry entry #70).
"""
from __future__ import annotations

import json

from agent_action_capsule import verify as verify_capsule

from capsule_ledger.conversation import digest_conversation_exchange
from capsule_ledger.examples.airline_engagement_pack import DEVELOPER, OPERATOR, load_conversations
from capsule_ledger.examples.tau2_conversation_exchange import (
    TAU2_MODEL_ID,
    TAU2_PROVIDER,
    seal_tau2_sim_exchange,
    tau2_sim_to_exchange_messages,
)


def _sim_with_tool_calls(sims: list[dict]) -> dict:
    return next(s for s in sims if any(m.get("tool_call_names") for m in s["messages"]))


def test_tau2_sim_conversation_seals_with_mesh_capsule_shape(signer):
    sims = load_conversations()
    sim = _sim_with_tool_calls(sims)

    capsule = seal_tau2_sim_exchange(sim, operator=OPERATOR, developer=DEVELOPER, signer=signer)

    result = verify_capsule(capsule)
    assert result.ok, [f.detail for f in result.findings]

    attestation = capsule["model_attestation"]
    assert attestation["model_id"] == TAU2_MODEL_ID
    assert attestation["provider"] == TAU2_PROVIDER
    compute_attestation = attestation["compute_attestation"]

    messages = tau2_sim_to_exchange_messages(sim)
    expected = digest_conversation_exchange(messages)
    assert compute_attestation["agent_input_digest"] == expected["agent_input_digest"]
    assert compute_attestation["agent_output_digest"] == expected["agent_output_digest"]
    assert compute_attestation["tool_calls_digest"] == expected["tool_calls_digest"]

    # tau2-bench's transcripts never carry a reasoning field -- the
    # sub-digest is absent, not fabricated, which is what proves the same
    # builder generalizes to a source engagement (Alchemy, Amplifier
    # Security) that DOES carry reasoning content: nothing here special-
    # cases tau2, the field is just genuinely missing from this input.
    assert expected["reasoning_digest"] is None
    assert "reasoning_digest" not in compute_attestation

    # digests-only: no raw conversation text ever enters the sealed capsule.
    blob = json.dumps(capsule)
    for m in sim["messages"]:
        content = m.get("content")
        if content:
            assert content not in blob


def test_tampering_a_tool_call_name_changes_the_tool_calls_digest(signer):
    sims = load_conversations()
    sim = _sim_with_tool_calls(sims)
    messages = tau2_sim_to_exchange_messages(sim)
    original = digest_conversation_exchange(messages)
    assert original["tool_calls_digest"] is not None

    tampered = [dict(m) for m in messages]
    for m in tampered:
        if m.get("tool_calls"):
            m["tool_calls"] = [{"name": "a_different_tool_call"}]
            break
    tampered_digests = digest_conversation_exchange(tampered)

    assert tampered_digests["tool_calls_digest"] != original["tool_calls_digest"]
    # tampering only the tool-call trail must not silently also change the
    # labeled digests it is NOT supposed to affect -- otherwise fold-scoped
    # disclosure of just the tool calls would leak information about the
    # prompt/response content through digest correlation.
    assert tampered_digests["agent_input_digest"] == original["agent_input_digest"]
    assert tampered_digests["agent_output_digest"] == original["agent_output_digest"]


def test_capsule_id_changes_if_a_digest_is_tampered_after_seal(signer):
    sims = load_conversations()
    sim = _sim_with_tool_calls(sims)
    capsule = seal_tau2_sim_exchange(sim, operator=OPERATOR, developer=DEVELOPER, signer=signer)

    tampered = json.loads(json.dumps(capsule))
    tampered["model_attestation"]["compute_attestation"]["tool_calls_digest"] = "0" * 64

    result = verify_capsule(tampered)
    assert not result.ok
    assert any(f.code == "capsule_id_mismatch" for f in result.findings)
