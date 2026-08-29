# SPDX-License-Identifier: Apache-2.0
"""``conversation_exchange``: one capsule per exchange (a tau2-bench
simulation, a live engagement's turn window, a mesh inference request/
response), carrying the SAME ``model_attestation.compute_attestation``
shape ``mesh_record_emitter.py``'s inference capsules carry --
``agent_input_digest``/``agent_output_digest`` over the exchange's own
turns, model provenance (``model_id``/``provider``, plus ``quant``/
``hardware`` when the caller has them), and the labeled sub-digests
``reasoning_digest``/``tool_calls_digest`` (CPB ``mesh-inference-exchange``
registry entry #70, ``scitt-payload-binding``'s
``spec/cpb-provisional-registry.md``).

[tau2-engagement-conversation-detail-capsules]: ONE capsule shape spans
mesh inference, tau2, and (once wired) the real Alchemy/Amplifier Security
engagements. The labeled sub-digests are what make tier-2 fold-scoped
disclosure possible: a holder can later disclose just the tool-call bytes
(``payload_store.PayloadStore``) without disclosing the prompt or reasoning
content, because each is committed under its own label rather than folded
into one opaque digest. Raw message content NEVER enters this capsule --
only digests; disclosure is always a separate, deliberate act.

``reasoning_digest``/``tool_calls_digest`` are OPTIONAL and simply absent
when the source conversation carries nothing under that label -- tau2-
bench's transcripts have no reasoning field at all, which is exactly the
"tau2-bench drops a field" case this shape must tolerate without a
fabricated digest over an empty placeholder. A real engagement transcript
that DOES carry full reasoning/tool-call detail sets both without any
change to this builder.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from agent_action_capsule import (
    AssuranceBlock,
    Capsule,
    Chain,
    ModelAttestation,
    compute_capsule_id,
    json_digest,
)

from ..guards.signing import Signer

__all__ = [
    "EVENT_CONVERSATION_EXCHANGE",
    "digest_conversation_exchange",
    "build_conversation_exchange_capsule",
]

_SPEC_VERSION = "draft-mih-scitt-agent-action-capsule-02"
_FORMAT_VERSION = "2"

EVENT_CONVERSATION_EXCHANGE = "conversation_exchange"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def digest_conversation_exchange(messages: Sequence[Mapping[str, Any]]) -> dict[str, str | None]:
    """Compute the mesh-shaped labeled sub-digests over one exchange's
    ``messages``.

    Each message is ``{"role": "user"|"assistant", "content": str,
    "tool_calls": [...] (optional), "reasoning": str (optional)}``.
    ``agent_input_digest`` commits the ordered ``user``-role turns (what was
    given to the agent); ``agent_output_digest`` commits the ordered
    ``assistant``-role turns (what the agent produced). ``tool_calls_digest``
    commits the flattened tool-call trail across every message, and
    ``reasoning_digest`` commits every message's own reasoning content --
    both ``None`` (not a digest over an empty list) when the conversation
    carries nothing under that label, so a producer can never be misread as
    having asserted "there were zero tool calls" when the source simply
    never told it either way.
    """
    input_turns = [{"role": m["role"], "content": m.get("content", "")} for m in messages if m.get("role") == "user"]
    output_turns = [
        {"role": m["role"], "content": m.get("content", "")} for m in messages if m.get("role") == "assistant"
    ]
    tool_calls = [tc for m in messages for tc in (m.get("tool_calls") or [])]
    reasoning_chunks = [m["reasoning"] for m in messages if m.get("reasoning")]

    return {
        "agent_input_digest": json_digest(input_turns),
        "agent_output_digest": json_digest(output_turns),
        "tool_calls_digest": json_digest(tool_calls) if tool_calls else None,
        "reasoning_digest": json_digest(reasoning_chunks) if reasoning_chunks else None,
    }


def build_conversation_exchange_capsule(
    *,
    session_id: str,
    exchange_id: str,
    messages: Sequence[Mapping[str, Any]],
    model_id: str,
    provider: str,
    operator: str,
    developer: str,
    signer: Signer,
    quant: str | None = None,
    hardware: str | None = None,
    runtime: str | None = None,
    chain_parent: str | None = None,
    chain_relation: str | None = None,
    timestamp: str | None = None,
    action_id: str | None = None,
) -> dict:
    """Seal one conversation exchange as a passive ``fyi`` capsule carrying
    ``model_attestation`` in the mesh inference capsule shape (see module
    docstring). Requires a live ``signer`` -- same fail-closed convention as
    every other builder in this package (an unsigned record is not a
    record).
    """
    if not messages:
        raise ValueError("messages must be non-empty -- there is no such thing as an empty exchange")

    digests = digest_conversation_exchange(messages)

    compute_attestation: dict[str, Any] = {
        "agent_input_digest": digests["agent_input_digest"],
        "agent_output_digest": digests["agent_output_digest"],
    }
    if digests["reasoning_digest"] is not None:
        compute_attestation["reasoning_digest"] = digests["reasoning_digest"]
    if digests["tool_calls_digest"] is not None:
        compute_attestation["tool_calls_digest"] = digests["tool_calls_digest"]
    if quant is not None:
        compute_attestation["quant"] = quant
    if hardware is not None:
        compute_attestation["hardware"] = hardware
    if runtime is not None:
        compute_attestation["runtime"] = runtime

    model_attestation = ModelAttestation(model_id=model_id, provider=provider, compute_attestation=compute_attestation)

    chain = Chain(parent_capsule_id=chain_parent, relation=chain_relation) if chain_parent else None
    capsule_obj = Capsule(
        spec_version=_SPEC_VERSION,
        format_version=_FORMAT_VERSION,
        action_id=action_id or f"conversation.exchange/{session_id}/{exchange_id}",
        action_type="fyi",
        operator=operator,
        developer=developer,
        timestamp=timestamp or _utc_now(),
        model_attestation=model_attestation,
        assurance=AssuranceBlock(
            attestation_mode="self_attested",
            effect_mode="not_applicable",
            ledger_mode="chained" if chain is not None else "standalone",
        ),
        chain=chain,
    )
    body = capsule_obj.to_dict()
    body["asg_payload"] = {
        "event": EVENT_CONVERSATION_EXCHANGE,
        "detail": {
            "session_id": session_id,
            "exchange_id": exchange_id,
            "message_count": len(messages),
        },
    }

    # Same digest-then-sign-then-reseal sequence as every other capsule
    # builder in this codebase: the signature is committed into the body
    # before capsule_id is computed, so a tampered signature is caught by
    # digest_mismatch on recompute rather than needing a separate
    # verification step.
    presig_digest = json_digest(body)
    body["asg_signature"] = {"key_id": signer.key_id, "alg": signer.algorithm, "sig": signer.sign(presig_digest)}

    capsule_id = compute_capsule_id(body)
    sealed = {"spec_version": body["spec_version"], "format_version": body["format_version"], "capsule_id": capsule_id}
    for k, v in body.items():
        if k not in sealed:
            sealed[k] = v
    return sealed
