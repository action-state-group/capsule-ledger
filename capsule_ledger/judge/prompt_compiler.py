# SPDX-License-Identifier: Apache-2.0
"""Outcomes -> judge-prompt compiler ([outcomes-to-judgeprompt-compiler-t3]):
bridges a confirmed pack outcome (``packs.schema.Outcome`` -- ``statement``
+ ``evidence_rule``) into a digest-pinned ``JudgePromptDefinition``, the
same role ``setup.compile_bridge`` plays for the forward/backward compiler
-- "the one place [an input] becomes something the next stage can
actually run against".

A judge prompt is never generated from the bare ``statement`` alone
(backward-llm-judge-architecture-design build spec, point 1): ``statement``
names WHAT is claimed, ``evidence_rule`` names WHAT COUNTS as confirming
it, and neither carries the domain framing a judge needs to read free-text
evidence sanely -- e.g. without being told a pack governs a read-only
investigation agent, a judge has no way to know that a write-shaped tool
call in the transcript is itself the anomaly. ``PackContextBlock`` is that
third, shared input: one block of domain framing every term's prompt in a
pack inherits, supplied once per pack rather than repeated per term.

Deterministic by construction -- this module makes no model call. A
model-assisted drafter for ``instructions`` prose (mirroring
``setup.prose_drafter``'s opt-in seam) is a natural follow-on, out of
scope here: the compiled instructions below are already a complete,
reviewable judge prompt, and a human confirms or edits them at T3
(``setup.confirm.confirm_prompt``) before anything is sealed -- drafting
QUALITY is a T3-review concern, not a compiler-correctness one.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..packs.schema import Outcome
from .errors import (
    DUPLICATE_LABEL,
    EMPTY_LABEL_SET,
    INVALID_PROMPT_ID,
    REFUSED_OUTCOME_NO_JUDGE_PROMPT,
    JudgeError,
)
from .prompt import PROMPT_ID_RE, JudgePromptDefinition

__all__ = ["DEFAULT_LABEL_SET", "PackContextBlock", "compile_judge_prompt"]

# Matches the verdict_schema convention ``compiler.terms_desk.TermDeclaration``
# already uses for a pass/fail term (the shape a compiled judge prompt's
# result eventually feeds into as a ``JudgeOrRuleSpec``) -- reused here so a
# prompt compiled by this module needs no relabeling to be cited from a
# terms document.
DEFAULT_LABEL_SET: tuple[str, ...] = ("pass", "fail")


@dataclass(frozen=True)
class PackContextBlock:
    """The shared domain framing every term's prompt in one pack inherits
    (build spec point 1's "pack-context block"). Free text on purpose --
    same "instructions are free text, digested as part of the prompt,
    never interpreted here" discipline ``JudgePromptDefinition.instructions``
    itself follows. E.g. a read-only-investigation-shaped pack's framing
    states the agent may query and read records but must never write,
    modify, or delete one, so a judge reading a transcript recognizes a
    write attempt as the anomaly it is rather than an unremarkable detail.
    """

    pack_id: str
    framing: str

    def __post_init__(self) -> None:
        if not self.pack_id or not self.pack_id.strip():
            raise ValueError("PackContextBlock.pack_id must be non-empty")
        if not self.framing or not self.framing.strip():
            raise ValueError("PackContextBlock.framing must be non-empty")


def compile_judge_prompt(
    outcome: Outcome,
    pack_context: PackContextBlock,
    *,
    version: str = "1.0.0",
    label_set: tuple[str, ...] = DEFAULT_LABEL_SET,
    model_id_hint: str | None = None,
) -> JudgePromptDefinition:
    """Compile one confirmed outcome's ``statement`` + ``evidence_rule``,
    framed by the pack's shared ``pack_context``, into a digest-pinned
    judge prompt.

    Refuses an outcome whose ``backward_verdict`` is REFUSED outright
    (``packs.schema``'s seeded refusal reasons) -- there is no evidence
    rule a judge could apply to an unbounded goal or an
    agent-caused-resolution claim; that path stays T4's (acknowledge the
    refusal), never a judge prompt.

    The returned prompt is a COMPILED CANDIDATE, not yet load-bearing --
    ``setup.confirm.confirm_prompt`` (T3) is where a human confirms or
    edits it and seals the final wording as a signed capsule.
    """
    if outcome.backward_verdict == "REFUSED":
        raise JudgeError(
            REFUSED_OUTCOME_NO_JUDGE_PROMPT,
            f"outcome {outcome.id!r} is REFUSED (backward_verdict=REFUSED) -- no evidence rule for a "
            "judge to apply; acknowledge the refusal (T4) instead of compiling a judge prompt for it",
        )

    if not label_set:
        raise JudgeError(EMPTY_LABEL_SET, "label_set must be a non-empty tuple of strings")
    if len(set(label_set)) != len(label_set):
        raise JudgeError(DUPLICATE_LABEL, f"label_set contains a duplicate label: {label_set!r}")

    instructions = (
        f"{pack_context.framing.strip()}\n\n"
        f"Outcome under review ({outcome.id}): {outcome.statement}\n\n"
        f"Evidence rule: {outcome.evidence_rule}\n\n"
        "Read the evidence provided below the line and decide which ONE label from the label set "
        "applies. Ground your label only in what the evidence actually shows -- never infer, assume, "
        "or extrapolate beyond it. Respond with exactly one label plus a short rationale citing the "
        "specific evidence that supports it."
    )

    prompt_id = f"{outcome.id.lower()}/{version}"
    if not PROMPT_ID_RE.match(prompt_id):
        raise JudgeError(
            INVALID_PROMPT_ID,
            f"outcome id {outcome.id!r} lower-cased to {outcome.id.lower()!r} does not produce a valid "
            f"prompt_id namespace for {prompt_id!r}",
        )

    return JudgePromptDefinition(
        prompt_id=prompt_id,
        label_set=tuple(label_set),
        instructions=instructions,
        model_id_hint=model_id_hint,
    )
