# SPDX-License-Identifier: Apache-2.0
"""``StaticScorer``: a deterministic, no-network, no-model-call ``Scorer``
reference implementation.

Two jobs: (1) proves the ``Scorer`` seam is genuinely swappable (BYOM) --
any object implementing ``score()`` works, this is simply the smallest one;
(2) gives tests and demos a fixed, reproducible judge result without a live
model call or an API key, matching this codebase's own no-network-in-tests
discipline for everything that isn't explicitly a model call.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..errors import SCORER_LABEL_NOT_IN_LABEL_SET, JudgeError
from ..prompt import JudgePromptDefinition
from ..scorer import JudgeEvidence, ScoreResult

__all__ = ["StaticScorer"]


@dataclass(frozen=True)
class StaticScorer:
    """Looks up ``(label, confidence)`` by ``evidence.evidence_text``
    verbatim; a caller wanting per-session results scripts a mapping keyed
    however it likes. ``default`` answers any evidence text not in
    ``responses`` -- omit it to make an unscripted evidence text a hard
    error instead of a silent guess."""

    responses: dict[str, tuple[str, float]] = field(default_factory=dict)
    model_id: str = "static-scorer/deterministic"
    default: tuple[str, float] | None = None

    def score(self, *, evidence: JudgeEvidence, prompt: JudgePromptDefinition) -> ScoreResult:
        if evidence.evidence_text in self.responses:
            label, confidence = self.responses[evidence.evidence_text]
        elif self.default is not None:
            label, confidence = self.default
        else:
            raise JudgeError(
                SCORER_LABEL_NOT_IN_LABEL_SET,
                f"StaticScorer has no scripted response for evidence_text {evidence.evidence_text!r} and no default",
            )
        if label not in prompt.label_set:
            raise JudgeError(
                SCORER_LABEL_NOT_IN_LABEL_SET,
                f"StaticScorer's scripted label {label!r} is not in prompt {prompt.prompt_id!r}'s "
                f"label_set {sorted(prompt.label_set)}",
            )
        return ScoreResult(label=label, confidence=confidence, model_id=self.model_id)
