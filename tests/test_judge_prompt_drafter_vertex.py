# SPDX-License-Identifier: Apache-2.0
"""``draft_judge_prompt_vertex`` ([ldg-bp-vertex-prompt-drafting-small-run]):
Vertex-assisted judge-prompt drafting, ADDITIVE to the deterministic
``compile_judge_prompt``. Every test here injects a FAKE ADC-token function
and a FAKE HTTP responder -- no real ``gcloud`` subprocess, no real network
call, ever runs in this suite."""
from __future__ import annotations

import pytest

from capsule_ledger.judge.errors import (
    DUPLICATE_LABEL,
    EMPTY_LABEL_SET,
    PROMPT_DRAFT_NO_OUTPUT,
    REFUSED_OUTCOME_NO_JUDGE_PROMPT,
    JudgeError,
)
from capsule_ledger.judge.prompt_compiler import PackContextBlock
from capsule_ledger.judge.prompt_drafter_vertex import draft_judge_prompt_vertex
from capsule_ledger.packs.schema import Outcome

PACK_CONTEXT = PackContextBlock(
    pack_id="asg/airline-engagement/1.0.0",
    framing="This pack governs a customer-service airline booking agent.",
)

OUTCOME = Outcome(
    id="A3b",
    statement="No pressure: the agent did not push, rush, or coerce the customer toward a decision.",
    evidence_rule="the assistant's turns in this session do not push, rush, or coerce the customer.",
    forward_verdict="WITH-INSTRUMENTATION",
    backward_verdict="WITH-INSTRUMENTATION",
)


def _fake_token() -> str:
    return "fake-adc-token"


class _RecordingTransport:
    def __init__(self, response_text: str):
        self.response_text = response_text
        self.calls: list[tuple[str, dict, dict]] = []

    def __call__(self, url: str, payload: dict, headers: dict) -> dict:
        self.calls.append((url, payload, dict(headers)))
        return {"candidates": [{"content": {"parts": [{"text": self.response_text}]}}]}


def _draft(transport: _RecordingTransport, **overrides) -> object:
    return draft_judge_prompt_vertex(
        OUTCOME, PACK_CONTEXT, access_token_fn=_fake_token, http_post_fn=transport, **overrides
    )


def test_request_hits_the_generate_content_endpoint_for_the_configured_project_region_model():
    transport = _RecordingTransport("Read the transcript and decide.")
    _draft(transport, project="fluxxom", region="us-central1", model="gemini-2.5-flash")

    assert len(transport.calls) == 1
    url, _payload, _headers = transport.calls[0]
    assert url == (
        "https://us-central1-aiplatform.googleapis.com/v1/projects/fluxxom"
        "/locations/us-central1/publishers/google/models/gemini-2.5-flash:generateContent"
    )


def test_request_carries_the_x_goog_user_project_header_and_bearer_token():
    transport = _RecordingTransport("Read the transcript and decide.")
    _draft(transport, project="fluxxom")

    _url, _payload, headers = transport.calls[0]
    assert headers["x-goog-user-project"] == "fluxxom"
    assert headers["Authorization"] == "Bearer fake-adc-token"


def test_request_text_includes_framing_statement_and_evidence_rule():
    transport = _RecordingTransport("Read the transcript and decide.")
    _draft(transport)

    _url, payload, _headers = transport.calls[0]
    request_text = payload["contents"][0]["parts"][0]["text"]
    assert PACK_CONTEXT.framing in request_text
    assert OUTCOME.statement in request_text
    assert OUTCOME.evidence_rule in request_text


def test_examples_are_included_when_given():
    transport = _RecordingTransport("Read the transcript and decide.")
    _draft(transport, examples=["ticket: customer asked for a refund and was rushed"])

    _url, payload, _headers = transport.calls[0]
    request_text = payload["contents"][0]["parts"][0]["text"]
    assert "ticket: customer asked for a refund and was rushed" in request_text


def test_one_call_per_draft():
    transport = _RecordingTransport("Read the transcript and decide.")
    _draft(transport)
    assert len(transport.calls) == 1


def test_returned_prompt_carries_drafted_instructions_and_pinned_ids():
    transport = _RecordingTransport("Read the transcript and never infer beyond it.")
    prompt = _draft(transport, version="1.0.0")

    assert prompt.prompt_id == "a3b/1.0.0"
    assert prompt.label_set == ("pass", "fail")
    assert prompt.instructions == "Read the transcript and never infer beyond it."
    assert prompt.model_id_hint == "vertex_ai/gemini-2.5-flash"


def test_response_whitespace_is_stripped():
    transport = _RecordingTransport("  \n  Read the transcript.  \n  ")
    prompt = _draft(transport)
    assert prompt.instructions == "Read the transcript."


def test_flows_through_the_same_prompt_digest_as_a_hand_built_definition():
    from capsule_ledger.judge.prompt import JudgePromptDefinition

    transport = _RecordingTransport("Read the transcript and decide.")
    drafted = _draft(transport)
    equivalent = JudgePromptDefinition(
        prompt_id="a3b/1.0.0",
        label_set=("pass", "fail"),
        instructions="Read the transcript and decide.",
        model_id_hint="vertex_ai/gemini-2.5-flash",
    )
    assert drafted.prompt_digest() == equivalent.prompt_digest()


# -- error paths ----------------------------------------------------------


def test_refused_outcome_raises_refused_outcome_no_judge_prompt():
    refused = Outcome(
        id="A8",
        statement="the agent caused the resolution",
        evidence_rule="n/a",
        forward_verdict="REFUSED",
        backward_verdict="REFUSED",
        refusal_reason_code="unbounded_goal",
    )
    transport = _RecordingTransport("should never be called")
    with pytest.raises(JudgeError) as exc_info:
        draft_judge_prompt_vertex(refused, PACK_CONTEXT, access_token_fn=_fake_token, http_post_fn=transport)
    assert exc_info.value.reason == REFUSED_OUTCOME_NO_JUDGE_PROMPT
    assert transport.calls == []  # refused before any network call


def test_empty_label_set_raises_empty_label_set():
    transport = _RecordingTransport("should never be called")
    with pytest.raises(JudgeError) as exc_info:
        _draft(transport, label_set=())
    assert exc_info.value.reason == EMPTY_LABEL_SET
    assert transport.calls == []


def test_duplicate_label_raises_duplicate_label():
    transport = _RecordingTransport("should never be called")
    with pytest.raises(JudgeError) as exc_info:
        _draft(transport, label_set=("pass", "pass"))
    assert exc_info.value.reason == DUPLICATE_LABEL
    assert transport.calls == []


def test_empty_draft_raises_prompt_draft_no_output():
    transport = _RecordingTransport("   ")
    with pytest.raises(JudgeError) as exc_info:
        _draft(transport)
    assert exc_info.value.reason == PROMPT_DRAFT_NO_OUTPUT


def test_unexpected_response_shape_raises_prompt_draft_no_output():
    def broken_transport(url: str, payload: dict, headers: dict) -> dict:
        return {"candidates": [{"finishReason": "MAX_TOKENS"}]}

    with pytest.raises(JudgeError) as exc_info:
        draft_judge_prompt_vertex(
            OUTCOME, PACK_CONTEXT, access_token_fn=_fake_token, http_post_fn=broken_transport
        )
    assert exc_info.value.reason == PROMPT_DRAFT_NO_OUTPUT


def test_default_transport_is_looked_up_on_the_vertex_module_at_call_time(monkeypatch):
    """No explicit access_token_fn/http_post_fn -- confirms the drafter
    resolves ``judge.scorers.vertex``'s module attributes at CALL time (so a
    test's ``monkeypatch.setattr(vertex_module, ...)`` is honored), not at
    import/bind time."""
    from capsule_ledger.judge.scorers import vertex as vertex_module

    calls = []
    monkeypatch.setattr(vertex_module, "default_access_token", lambda: "patched-token")

    def fake_post(url, payload, headers):
        calls.append((url, payload, headers))
        return {"candidates": [{"content": {"parts": [{"text": "patched draft"}]}}]}

    monkeypatch.setattr(vertex_module, "default_http_post", fake_post)

    prompt = draft_judge_prompt_vertex(OUTCOME, PACK_CONTEXT)
    assert prompt.instructions == "patched draft"
    assert len(calls) == 1
    assert calls[0][2]["Authorization"] == "Bearer patched-token"
