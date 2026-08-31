# SPDX-License-Identifier: Apache-2.0
"""``VertexScorer`` ([ldg-bp-vertex-scorer-live-run]): stdlib-only Gemini-on-
Vertex ``Scorer``. Every test here injects a FAKE ADC-token function and a
FAKE HTTP responder -- no real ``gcloud`` subprocess, no real network call,
ever runs in this suite. Tests assert the actual request shape (endpoint,
the ``x-goog-user-project`` header, the label-constrained prompt) rather
than trusting the scorer's own claim of what it sent."""
from __future__ import annotations

import json

import pytest

from capsule_ledger.judge.errors import SCORER_LABEL_NOT_IN_LABEL_SET, VERTEX_RESPONSE_MALFORMED, JudgeError
from capsule_ledger.judge.prompt import JudgePromptDefinition
from capsule_ledger.judge.scorer import JudgeEvidence
from capsule_ledger.judge.scorers.vertex import VertexCallError, VertexScorer

PROMPT = JudgePromptDefinition(
    prompt_id="conversation.no_pressure/1.0.0",
    label_set=("pass", "fail"),
    instructions="Did the agent avoid pressuring the customer toward a decision?",
)

EVIDENCE = JudgeEvidence(
    session_id="sess-1",
    turn_capsule_ids=("cap-1", "cap-2"),
    evidence_text="assistant: you should decide right now or lose the offer",
)


def _fake_token() -> str:
    return "fake-adc-token"


class _RecordingTransport:
    """A fake ``http_post_fn`` that captures every call it receives and
    returns a scripted Gemini ``generateContent``-shaped response -- the
    seam the task asks CI to fake ("a fake ADC-token + fake HTTP
    responder")."""

    def __init__(self, response_text: str, *, model_version: str | None = "gemini-2.5-flash-002"):
        self.response_text = response_text
        self.model_version = model_version
        self.calls: list[tuple[str, dict, dict]] = []

    def __call__(self, url: str, payload: dict, headers: dict) -> dict:
        self.calls.append((url, payload, dict(headers)))
        data = {"candidates": [{"content": {"parts": [{"text": self.response_text}]}}]}
        if self.model_version is not None:
            data["modelVersion"] = self.model_version
        return data


def _scorer(transport: _RecordingTransport, **overrides) -> VertexScorer:
    return VertexScorer(access_token_fn=_fake_token, http_post_fn=transport, **overrides)


# -- request shape ----------------------------------------------------------


def test_request_hits_the_generate_content_endpoint_for_the_configured_project_region_model():
    transport = _RecordingTransport(json.dumps({"label": "pass", "confidence": 0.9, "rationale": "no pressure seen"}))
    scorer = _scorer(transport, project="fluxxom", region="us-central1", model="gemini-2.5-flash")
    scorer.score(evidence=EVIDENCE, prompt=PROMPT)

    assert len(transport.calls) == 1
    url, _payload, _headers = transport.calls[0]
    assert url == (
        "https://us-central1-aiplatform.googleapis.com/v1/projects/fluxxom"
        "/locations/us-central1/publishers/google/models/gemini-2.5-flash:generateContent"
    )


def test_request_carries_the_x_goog_user_project_header_and_bearer_token():
    transport = _RecordingTransport(json.dumps({"label": "pass", "confidence": 0.9}))
    scorer = _scorer(transport, project="fluxxom")
    scorer.score(evidence=EVIDENCE, prompt=PROMPT)

    _url, _payload, headers = transport.calls[0]
    assert headers["x-goog-user-project"] == "fluxxom"
    assert headers["Authorization"] == "Bearer fake-adc-token"


def test_request_prompt_is_label_constrained_and_includes_instructions_and_evidence():
    transport = _RecordingTransport(json.dumps({"label": "fail", "confidence": 0.8}))
    scorer = _scorer(transport)
    scorer.score(evidence=EVIDENCE, prompt=PROMPT)

    _url, payload, _headers = transport.calls[0]
    request_text = payload["contents"][0]["parts"][0]["text"]
    assert PROMPT.instructions in request_text
    assert EVIDENCE.evidence_text in request_text
    assert "'pass'" in request_text and "'fail'" in request_text
    assert "JSON" in request_text


def test_one_call_per_score_not_one_call_per_label():
    # Unlike DeepEvalScorer's per-label GEval loop -- the cost shape the
    # live-run task calls out to keep a real corpus-scale run affordable.
    transport = _RecordingTransport(json.dumps({"label": "pass", "confidence": 1.0}))
    scorer = _scorer(transport)
    scorer.score(evidence=EVIDENCE, prompt=PROMPT)
    assert len(transport.calls) == 1


def test_thinking_budget_temperature_and_seed_are_digest_safe_sampling_params():
    transport = _RecordingTransport(json.dumps({"label": "pass", "confidence": 1.0}))
    scorer = _scorer(transport, temperature=0.2, thinking_budget=64, max_output_tokens=512, seed=42)
    result = scorer.score(evidence=EVIDENCE, prompt=PROMPT)
    assert result.sampling_params == {
        "temperature_micros": 200_000,
        "thinking_budget": 64,
        "max_output_tokens": 512,
        "seed": 42,
    }
    for value in result.sampling_params.values():
        assert isinstance(value, int)


# -- seed / entropy binding ([account-fold-core-unify]) ---------------------


def test_explicit_seed_is_sent_in_generation_config_and_echoed_in_sampling_params():
    transport = _RecordingTransport(json.dumps({"label": "pass", "confidence": 1.0}))
    scorer = _scorer(transport, seed=12345)
    result = scorer.score(evidence=EVIDENCE, prompt=PROMPT)

    _url, payload, _headers = transport.calls[0]
    assert payload["generationConfig"]["seed"] == 12345
    assert result.sampling_params["seed"] == 12345


def test_explicit_seed_pins_every_call_from_the_same_scorer_instance():
    transport = _RecordingTransport(json.dumps({"label": "pass", "confidence": 1.0}))
    scorer = _scorer(transport, seed=999)
    scorer.score(evidence=EVIDENCE, prompt=PROMPT)
    scorer.score(evidence=EVIDENCE, prompt=PROMPT)

    seeds = [call[1]["generationConfig"]["seed"] for call in transport.calls]
    assert seeds == [999, 999]


def test_no_seed_given_draws_a_fresh_real_seed_every_call_not_a_shared_or_null_one():
    transport = _RecordingTransport(json.dumps({"label": "pass", "confidence": 1.0}))
    scorer = _scorer(transport)  # seed=None (default)
    scorer.score(evidence=EVIDENCE, prompt=PROMPT)
    scorer.score(evidence=EVIDENCE, prompt=PROMPT)

    seeds = [call[1]["generationConfig"]["seed"] for call in transport.calls]
    assert all(isinstance(s, int) for s in seeds)
    assert seeds[0] != seeds[1]  # a fresh draw per call, not a fixed default


# -- response parsing ---------------------------------------------------


def test_parses_label_confidence_and_rationale():
    transport = _RecordingTransport(json.dumps({"label": "pass", "confidence": 0.73, "rationale": "no pressure language found"}))
    scorer = _scorer(transport)
    result = scorer.score(evidence=EVIDENCE, prompt=PROMPT)
    assert result.label == "pass"
    assert result.confidence == 0.73
    assert result.rationale == "no pressure language found"
    assert result.model_id == "vertex_ai/gemini-2.5-flash"
    assert result.model_version == "gemini-2.5-flash-002"


def test_strips_markdown_json_fence_before_parsing():
    fenced = "```json\n" + json.dumps({"label": "fail", "confidence": 0.5}) + "\n```"
    transport = _RecordingTransport(fenced)
    scorer = _scorer(transport)
    result = scorer.score(evidence=EVIDENCE, prompt=PROMPT)
    assert result.label == "fail"


def test_confidence_defaults_to_one_when_omitted():
    transport = _RecordingTransport(json.dumps({"label": "pass"}))
    scorer = _scorer(transport)
    result = scorer.score(evidence=EVIDENCE, prompt=PROMPT)
    assert result.confidence == 1.0
    assert result.rationale is None


# -- error paths: every one must actually be reachable, not just declared --


def test_malformed_json_response_raises_vertex_response_malformed():
    transport = _RecordingTransport("this is not json at all")
    scorer = _scorer(transport)
    with pytest.raises(JudgeError) as exc_info:
        scorer.score(evidence=EVIDENCE, prompt=PROMPT)
    assert exc_info.value.reason == VERTEX_RESPONSE_MALFORMED


def test_missing_label_key_raises_vertex_response_malformed():
    transport = _RecordingTransport(json.dumps({"confidence": 0.5}))
    scorer = _scorer(transport)
    with pytest.raises(JudgeError) as exc_info:
        scorer.score(evidence=EVIDENCE, prompt=PROMPT)
    assert exc_info.value.reason == VERTEX_RESPONSE_MALFORMED


def test_label_outside_label_set_raises_scorer_label_not_in_label_set():
    transport = _RecordingTransport(json.dumps({"label": "maybe", "confidence": 0.5}))
    scorer = _scorer(transport)
    with pytest.raises(JudgeError) as exc_info:
        scorer.score(evidence=EVIDENCE, prompt=PROMPT)
    assert exc_info.value.reason == SCORER_LABEL_NOT_IN_LABEL_SET


def test_confidence_out_of_range_raises_vertex_response_malformed():
    transport = _RecordingTransport(json.dumps({"label": "pass", "confidence": 1.5}))
    scorer = _scorer(transport)
    with pytest.raises(JudgeError) as exc_info:
        scorer.score(evidence=EVIDENCE, prompt=PROMPT)
    assert exc_info.value.reason == VERTEX_RESPONSE_MALFORMED


def test_unexpected_response_shape_raises_vertex_response_malformed():
    def broken_transport(url: str, payload: dict, headers: dict) -> dict:
        return {"candidates": [{"finishReason": "MAX_TOKENS"}]}

    scorer = _scorer(broken_transport)
    with pytest.raises(JudgeError) as exc_info:
        scorer.score(evidence=EVIDENCE, prompt=PROMPT)
    assert exc_info.value.reason == VERTEX_RESPONSE_MALFORMED
    assert "MAX_TOKENS" in str(exc_info.value)


# -- default transport is real, but its retry/backoff logic is testable in
#    isolation by faking urllib itself (never gcloud, never a live socket) --


def test_default_http_post_retries_a_retryable_status_then_succeeds(monkeypatch):
    import io
    import urllib.error

    from capsule_ledger.judge.scorers import vertex as vertex_module

    attempts = {"n": 0}

    class _FakeResponse:
        def __init__(self, body: bytes):
            self._body = body

        def read(self) -> bytes:
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise urllib.error.HTTPError(request.full_url, 503, "unavailable", {}, io.BytesIO(b"try again"))
        return _FakeResponse(json.dumps({"ok": True}).encode("utf-8"))

    monkeypatch.setattr(vertex_module.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(vertex_module.time, "sleep", lambda _seconds: None)

    result = vertex_module.default_http_post("https://example.invalid/", {"a": 1}, {"h": "v"})
    assert result == {"ok": True}
    assert attempts["n"] == 2


def test_default_http_post_raises_vertex_call_error_on_non_retryable_status(monkeypatch):
    import io
    import urllib.error

    from capsule_ledger.judge.scorers import vertex as vertex_module

    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 400, "bad request", {}, io.BytesIO(b'{"error": "bad request"}'))

    monkeypatch.setattr(vertex_module.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(VertexCallError):
        vertex_module.default_http_post("https://example.invalid/", {}, {})


def test_default_access_token_raises_on_gcloud_failure(monkeypatch):
    from capsule_ledger.judge.scorers import vertex as vertex_module

    class _FakeCompletedProcess:
        returncode = 1
        stdout = ""
        stderr = "not logged in"

    monkeypatch.setattr(vertex_module, "_cached_token", None)
    monkeypatch.setattr(vertex_module, "_cached_token_expiry", 0.0)
    monkeypatch.setattr(vertex_module.subprocess, "run", lambda *a, **k: _FakeCompletedProcess())

    with pytest.raises(VertexCallError):
        vertex_module.default_access_token()
