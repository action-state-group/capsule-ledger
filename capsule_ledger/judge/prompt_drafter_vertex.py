# SPDX-License-Identifier: Apache-2.0
"""Vertex-assisted judge-prompt drafting ([ldg-bp-vertex-prompt-drafting-small-run]):
an OPT-IN model-assisted drafter for a judge prompt's ``instructions`` text --
mirrors ``setup.prose_drafter``'s seam and answers ``prompt_compiler.py``'s
own noted follow-on ("A model-assisted drafter for ``instructions`` prose ...
is a natural follow-on"). ADDITIVE to ``compile_judge_prompt`` (the
deterministic, offline, no-key compiler): this module does not replace it,
and produces the SAME ``JudgePromptDefinition`` shape, so either one flows
through the SAME T3 ``setup.confirm.confirm_prompt`` seam UNCHANGED -- a
human still owns and seals the final wording regardless of which one drafted
the candidate; the model only drafts.

Reuses the SAME ADC+REST transport ``judge.scorers.vertex`` builds for
``VertexScorer`` (``default_access_token``/``default_http_post``, looked up
on the module AT CALL TIME so a test's
``monkeypatch.setattr(vertex_module, ...)`` is honored) -- no second Vertex
client implementation.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from ..packs.schema import Outcome
from .errors import (
    DUPLICATE_LABEL,
    EMPTY_LABEL_SET,
    INVALID_PROMPT_ID,
    PROMPT_DRAFT_NO_OUTPUT,
    REFUSED_OUTCOME_NO_JUDGE_PROMPT,
    JudgeError,
)
from .prompt import PROMPT_ID_RE, JudgePromptDefinition
from .prompt_compiler import DEFAULT_LABEL_SET, PackContextBlock
from .scorers import vertex as vertex_module

__all__ = ["draft_judge_prompt_vertex"]

_DEFAULT_PROJECT = "fluxxom"
_DEFAULT_REGION = "us-central1"
_DEFAULT_MODEL = "gemini-2.5-flash"


def _build_draft_request_text(
    outcome: Outcome, pack_context: PackContextBlock, examples: Sequence[str] | None
) -> str:
    examples_block = ""
    if examples:
        rendered = "\n".join(f"  - {example}" for example in examples)
        examples_block = f"\n\nExample ticket(s) for cold-start calibration (do not copy verbatim):\n{rendered}"
    return (
        f"{pack_context.framing.strip()}\n\n"
        f"Draft the INSTRUCTIONS text for a judge prompt that decides outcome {outcome.id!r}.\n\n"
        f"Statement: {outcome.statement}\n"
        f"Evidence rule: {outcome.evidence_rule}"
        f"{examples_block}\n\n"
        "Write ONE tight paragraph a judge model will read immediately before a transcript, telling "
        "it exactly what to look for in the evidence and how to decide between the labels in the "
        "label set. Ground it ONLY in the statement and evidence rule above -- never invent a fact, "
        "number, or rule beyond them. Respond with ONLY the instructions paragraph -- no preamble, "
        "no markdown, no JSON, no label restatement (the label set is appended separately)."
    )


def draft_judge_prompt_vertex(
    outcome: Outcome,
    pack_context: PackContextBlock,
    examples: Sequence[str] | None = None,
    *,
    project: str = _DEFAULT_PROJECT,
    region: str = _DEFAULT_REGION,
    model: str = _DEFAULT_MODEL,
    version: str = "1.0.0",
    label_set: tuple[str, ...] = DEFAULT_LABEL_SET,
    max_output_tokens: int = 512,
    temperature: float = 0.2,
    access_token_fn: Callable[[], str] | None = None,
    http_post_fn: Callable[[str, dict, Mapping[str, str]], dict] | None = None,
) -> JudgePromptDefinition:
    """Ask ``gemini-2.5-flash`` (via the SAME ADC+REST client
    ``VertexScorer`` uses) to draft a ``JudgePromptDefinition.instructions``
    paragraph from a confirmed outcome's ``statement`` + ``evidence_rule``,
    framed by the pack's shared ``pack_context`` (+ optional cold-start
    example tickets). This is a COMPILED CANDIDATE, exactly like
    ``compile_judge_prompt``'s return -- not yet load-bearing;
    ``setup.confirm.confirm_prompt`` (T3) is where a human confirms or edits
    it and seals the final wording.

    Makes ONE real, billed Vertex call unless ``access_token_fn``/
    ``http_post_fn`` are overridden with fakes (e.g. in a test)."""
    if outcome.backward_verdict == "REFUSED":
        raise JudgeError(
            REFUSED_OUTCOME_NO_JUDGE_PROMPT,
            f"outcome {outcome.id!r} is REFUSED (backward_verdict=REFUSED) -- no evidence rule for a "
            "judge to apply; acknowledge the refusal (T4) instead of drafting a judge prompt for it",
        )
    if not label_set:
        raise JudgeError(EMPTY_LABEL_SET, "label_set must be a non-empty tuple of strings")
    if len(set(label_set)) != len(label_set):
        raise JudgeError(DUPLICATE_LABEL, f"label_set contains a duplicate label: {label_set!r}")

    prompt_id = f"{outcome.id.lower()}/{version}"
    if not PROMPT_ID_RE.match(prompt_id):
        raise JudgeError(
            INVALID_PROMPT_ID,
            f"outcome id {outcome.id!r} lower-cased to {outcome.id.lower()!r} does not produce a valid "
            f"prompt_id namespace for {prompt_id!r}",
        )

    token_fn = access_token_fn or vertex_module.default_access_token
    post_fn = http_post_fn or vertex_module.default_http_post

    url = (
        f"https://{region}-aiplatform.googleapis.com/v1/projects/{project}"
        f"/locations/{region}/publishers/google/models/{model}:generateContent"
    )
    payload = {
        "contents": [
            {"role": "user", "parts": [{"text": _build_draft_request_text(outcome, pack_context, examples)}]}
        ],
        "generationConfig": {
            "maxOutputTokens": max_output_tokens,
            "temperature": temperature,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    headers = {
        "Authorization": f"Bearer {token_fn()}",
        "x-goog-user-project": project,
        "Content-Type": "application/json",
    }
    data = post_fn(url, payload, headers)
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as exc:
        raise JudgeError(PROMPT_DRAFT_NO_OUTPUT, f"unexpected Gemini response shape: {data!r}") from exc

    instructions = text.strip()
    if not instructions:
        raise JudgeError(PROMPT_DRAFT_NO_OUTPUT, f"Gemini returned an empty draft for outcome {outcome.id!r}")

    return JudgePromptDefinition(
        prompt_id=prompt_id,
        label_set=tuple(label_set),
        instructions=instructions,
        model_id_hint=f"vertex_ai/{model}",
    )
