# SPDX-License-Identifier: Apache-2.0
"""``VertexScorer``: a stdlib-only ``Scorer`` that calls Gemini on Vertex AI
over REST, via the caller's own ``gcloud`` ADC session -- no ``deepeval``,
no ``litellm``, no ``vertexai`` SDK dependency (``[ldg-bp-vertex-scorer-live-run]``:
the only real-model scorer this repo ships, ``DeepEvalScorer``, routes
``--model`` to DeepEval's OpenAI default and cannot hit Vertex at all).

The transport is the proven pattern from ``record-grounding-bench``'s
``llm/vertex.py`` (live-tested against GCP project ``fluxxom``): an ADC
access token from ``gcloud auth print-access-token``, POSTed to the
aiplatform ``generateContent`` endpoint with an explicit
``x-goog-user-project`` header -- found empirically there that Vertex 403s
on user ADC without it, a wrinkle undocumented anywhere obvious.

**One call per term, not one call per label** (unlike ``DeepEvalScorer``'s
G-Eval wrapper, which runs one model call per candidate label): the prompt
already carries the prompt's closed ``label_set`` and asks for a single
JSON verdict, so scoring N labels costs one call, not N -- the cost shape
the live-run task calls out to keep a real Vertex run affordable at
corpus scale (calls = sessions x terms, not sessions x terms x labels).

**Two injectable seams, exactly where CI needs to cut in a fake** (no real
network, no real ``gcloud`` subprocess in tests): ``access_token_fn`` (default
``default_access_token``, cached gcloud ADC) and ``http_post_fn`` (default
``default_http_post``, real ``urllib`` POST with retry/backoff on 429/5xx).
``VertexScorer.score`` builds the request URL, payload, and headers itself
(including ``x-goog-user-project``) and hands them to ``http_post_fn`` --
so a test asserting the request shape (endpoint, header, label-constrained
prompt text) reads them directly off what ``score`` constructed, without
needing to fake ``urllib`` at all.
"""
from __future__ import annotations

import json
import random
import re
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from ..errors import SCORER_LABEL_NOT_IN_LABEL_SET, VERTEX_RESPONSE_MALFORMED, JudgeError
from ..prompt import JudgePromptDefinition
from ..scorer import JudgeEvidence, ScoreResult

__all__ = [
    "VertexCallError",
    "VertexScorer",
    "default_access_token",
    "default_http_post",
]

_DEFAULT_PROJECT = "fluxxom"
_DEFAULT_REGION = "us-central1"
_DEFAULT_MODEL = "gemini-2.5-flash"

_MAX_RETRIES = 5
_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
# Real Vertex access tokens last ~1h; refresh a bit early rather than risk
# a request racing token expiry mid-flight (rgb's llm/vertex.py finding).
_TOKEN_REFRESH_MARGIN_SECONDS = 120

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$")


class VertexCallError(RuntimeError):
    pass


# -- default access-token provider (module-cached, real gcloud subprocess) --

_cached_token: str | None = None
_cached_token_expiry: float = 0.0


def default_access_token() -> str:
    global _cached_token, _cached_token_expiry
    now = time.monotonic()
    if _cached_token is not None and now < _cached_token_expiry:
        return _cached_token
    result = subprocess.run(
        ["gcloud", "auth", "print-access-token"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise VertexCallError(f"gcloud auth print-access-token failed: {result.stderr.strip()}")
    token = result.stdout.strip()
    _cached_token = token
    _cached_token_expiry = now + 3600 - _TOKEN_REFRESH_MARGIN_SECONDS
    return token


# -- default HTTP transport (real urllib POST, retry/backoff on 429/5xx) --


def default_http_post(url: str, payload: dict, headers: Mapping[str, str]) -> dict:
    body_bytes = json.dumps(payload).encode("utf-8")
    last_error: VertexCallError | None = None
    for attempt in range(_MAX_RETRIES):
        request = urllib.request.Request(url, data=body_bytes, headers=dict(headers), method="POST")
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="replace")
            last_error = VertexCallError(f"Vertex call to {url} failed ({exc.code}): {response_body}")
            if exc.code not in _RETRYABLE_STATUS_CODES or attempt == _MAX_RETRIES - 1:
                raise last_error from exc
            # Exponential backoff with jitter: 1-2s, 2-4s, 4-8s, 8-16s --
            # bounded at 5 attempts total, not an unbounded retry loop.
            time.sleep((2**attempt) * (1 + random.random()))
    raise last_error or VertexCallError(f"Vertex call to {url} failed after {_MAX_RETRIES} attempts")


def _build_request_text(prompt: JudgePromptDefinition, evidence: JudgeEvidence) -> str:
    label_list = ", ".join(repr(label) for label in prompt.label_set)
    return (
        f"{prompt.instructions}\n\n"
        f"---\nEvidence:\n{evidence.evidence_text}\n---\n\n"
        "Respond with ONLY a single JSON object (no markdown code fences, no other text) of "
        f'the exact shape {{"label": <one of {label_list}>, "confidence": <float between 0.0 '
        f'and 1.0>, "rationale": <short string citing the specific evidence>}}. The "label" '
        f"value MUST be exactly one of: {label_list}."
    )


def _current_default_access_token() -> str:
    # Indirection so a test's ``monkeypatch.setattr(vertex_module,
    # "default_access_token", fake)`` is honored by a ``VertexScorer()``
    # constructed with no explicit ``access_token_fn`` -- a dataclass
    # ``field(default=default_access_token)`` would instead bind today's
    # function OBJECT at class-definition time, permanently, before any
    # test gets a chance to monkeypatch the module attribute.
    return default_access_token()


def _current_default_http_post(url: str, payload: dict, headers: Mapping[str, str]) -> dict:
    return default_http_post(url, payload, headers)


def _parse_response_text(text: str, label_set: tuple[str, ...]) -> tuple[str, float, str | None]:
    stripped = _FENCE_RE.sub("", text.strip()).strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise JudgeError(VERTEX_RESPONSE_MALFORMED, f"Gemini response was not valid JSON: {text!r}") from exc
    if not isinstance(parsed, dict) or "label" not in parsed:
        raise JudgeError(
            VERTEX_RESPONSE_MALFORMED, f"Gemini response JSON is missing a 'label' field: {parsed!r}"
        )
    label = parsed["label"]
    if label not in label_set:
        raise JudgeError(
            SCORER_LABEL_NOT_IN_LABEL_SET,
            f"VertexScorer received label {label!r}, not in prompt's label_set {sorted(label_set)}",
        )
    confidence = float(parsed.get("confidence", 1.0))
    if not 0.0 <= confidence <= 1.0:
        raise JudgeError(VERTEX_RESPONSE_MALFORMED, f"Gemini response confidence {confidence!r} is outside [0.0, 1.0]")
    rationale = parsed.get("rationale")
    return label, confidence, (str(rationale) if rationale is not None else None)


@dataclass
class VertexScorer:
    """Scores one ``JudgeEvidence``/``JudgePromptDefinition`` pair with a
    single Gemini ``generateContent`` call (BYOM, keyless -- ADC only).

    ``project`` defaults to ``fluxxom`` (Steven's live ADC project, per the
    live-run task); override for a different GCP project. ``thinking_budget=0``
    disables Gemini 2.5's extended thinking by default -- rgb's own
    ``llm/vertex.py`` found a small ``max_output_tokens`` combined with
    default thinking silently consumes the whole budget on thinking tokens
    and returns an empty response (``finishReason: MAX_TOKENS``, no
    ``parts``) for tasks, like this one, that don't need deep reasoning.
    """

    project: str = _DEFAULT_PROJECT
    region: str = _DEFAULT_REGION
    model: str = _DEFAULT_MODEL
    max_output_tokens: int = 1024
    temperature: float = 0.0
    thinking_budget: int = 0
    access_token_fn: Callable[[], str] = field(default=_current_default_access_token)
    http_post_fn: Callable[[str, dict, Mapping[str, str]], dict] = field(default=_current_default_http_post)

    def score(self, *, evidence: JudgeEvidence, prompt: JudgePromptDefinition) -> ScoreResult:
        url = (
            f"https://{self.region}-aiplatform.googleapis.com/v1/projects/{self.project}"
            f"/locations/{self.region}/publishers/google/models/{self.model}:generateContent"
        )
        payload = {
            "contents": [{"role": "user", "parts": [{"text": _build_request_text(prompt, evidence)}]}],
            "generationConfig": {
                "maxOutputTokens": self.max_output_tokens,
                "temperature": self.temperature,
                "thinkingConfig": {"thinkingBudget": self.thinking_budget},
            },
        }
        headers = {
            "Authorization": f"Bearer {self.access_token_fn()}",
            "x-goog-user-project": self.project,
            "Content-Type": "application/json",
        }
        data = self.http_post_fn(url, payload, headers)
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as exc:
            finish_reason = None
            try:
                finish_reason = data["candidates"][0].get("finishReason")
            except (KeyError, IndexError):
                pass
            hint = (
                f" (finishReason={finish_reason!r} -- likely max_output_tokens was too small, "
                "possibly consumed entirely by thinking tokens; raise max_output_tokens or check "
                "thinking_budget)"
                if finish_reason == "MAX_TOKENS"
                else ""
            )
            raise JudgeError(
                VERTEX_RESPONSE_MALFORMED, f"unexpected Gemini response shape: {data!r}{hint}"
            ) from exc

        label, confidence, rationale = _parse_response_text(text, prompt.label_set)
        return ScoreResult(
            label=label,
            confidence=confidence,
            model_id=f"vertex_ai/{self.model}",
            model_version=data.get("modelVersion"),
            sampling_params={
                "temperature_micros": int(round(self.temperature * 1_000_000)),
                "thinking_budget": self.thinking_budget,
                "max_output_tokens": self.max_output_tokens,
            },
            rationale=rationale,
        )
