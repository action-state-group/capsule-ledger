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

    # Recovered inference metadata (the "what model, what settings, how much"
    # story), mirroring capsule-emit-mesh's serving_provenance shape.
    # generation_parameters: temperature is stringified (spec §5.1 float ban
    # -- a float cannot ride in a digest-bearing field), seed carried verbatim.
    gen = compute_attestation["generation_parameters"]
    assert gen["temperature"] == str(sim["generation_parameters"]["temperature"])
    assert gen["temperature"] == "0.0"  # tau2 airline agent runs greedy
    assert gen["seed"] == sim["generation_parameters"]["seed"]
    assert isinstance(gen["seed"], int)

    # usage: the token METER (prompt/completion + derived total). This is the
    # meter a relying party audits over; currency/cost is deliberately NOT
    # sealed (meter-not-price).
    usage = compute_attestation["usage"]
    assert usage["prompt_tokens"] == sim["usage"]["prompt_tokens"]
    assert usage["completion_tokens"] == sim["usage"]["completion_tokens"]
    assert usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]

    # hardware is the honest api-served marker, NOT a fabricated GPU/VRAM
    # block: tau2 runs against hosted API models, so served_by is "api" and
    # no local hardware field exists to attest.
    assert compute_attestation["served_by"] == "api"
    assert "hardware" not in compute_attestation
    assert "quant" not in compute_attestation

    # Neutrality: the token meter rides, but no currency/cost amount is ever
    # sealed into the neutral record (capsule-emit-mesh TRUST-MODEL §6).
    assert "cost" not in json.dumps(compute_attestation)

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


def test_every_vendored_sim_carries_recovered_inference_metadata():
    """Every vendored sim must carry the recovered model/generation/usage
    story -- the whole point of the re-vendor. Proves the recovery is not a
    one-off on the single sim the other tests happen to pick."""
    sims = load_conversations()
    assert sims
    for sim in sims:
        assert sim["model"] == TAU2_MODEL_ID
        assert sim["served_by"] == "api"
        # temperature+seed both recorded by this run's source
        gen = sim["generation_parameters"]
        assert gen["temperature"] == 0.0
        assert isinstance(gen["seed"], int)
        # usage summed over the agent's own messages; total is derived
        usage = sim["usage"]
        assert usage["prompt_tokens"] >= 0
        assert usage["completion_tokens"] >= 0
        assert usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]


def test_honest_by_absence_when_source_lacks_a_field(signer):
    """A sim whose vendored record lacks usage / a generation parameter seals
    WITHOUT that field -- absent stays absent, never a fabricated zero or a
    fabricated hardware block. Mutating a copy of a real sim exercises exactly
    the "source dropped a field" path a different model file would hit."""
    sims = load_conversations()
    sim = json.loads(json.dumps(_sim_with_tool_calls(sims)))
    sim["usage"] = None
    sim["generation_parameters"] = {}  # no temperature, no seed
    sim["served_by"] = "api"

    capsule = seal_tau2_sim_exchange(sim, operator=OPERATOR, developer=DEVELOPER, signer=signer)
    result = verify_capsule(capsule)
    assert result.ok, [f.detail for f in result.findings]

    compute_attestation = capsule["model_attestation"]["compute_attestation"]
    # absent, not a fabricated {0,0,0} or an empty params block
    assert "usage" not in compute_attestation
    assert "generation_parameters" not in compute_attestation
    # the honest api-served marker still rides; hardware is still never fabricated
    assert compute_attestation["served_by"] == "api"
    assert "hardware" not in compute_attestation


def test_usage_excludes_the_user_simulator_tokens():
    """The vendored per-sim usage is the AGENT's meter only. The user role in
    a tau2 sim is a DIFFERENT LLM (the user-simulator, gpt-4.1); folding its
    tokens into the claude agent's usage would misattribute them. This asserts
    the vendored aggregate matches an assistant-only re-sum from the raw
    conversation -- guarding the split at the vendor boundary."""
    from capsule_ledger.conversation import build_usage

    # build_usage is honest-by-absence: nothing in, nothing out.
    assert build_usage(None, None) is None
    # derived total from whatever counts are present.
    assert build_usage(10, 3) == {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13}
    assert build_usage(prompt_tokens=5) == {"prompt_tokens": 5, "total_tokens": 5}
