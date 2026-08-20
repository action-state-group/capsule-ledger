# SPDX-License-Identifier: Apache-2.0
"""The ``Scorer`` seam: the judge harness does NOT implement scoring itself
(the outcomes-to-actions design doc §2 -- OSS rubric-eval frameworks already
solve this, and churn faster than our claims format should). ``Scorer`` is a
thin, swappable protocol; ``scorers/deepeval_scorer.py`` is the default
(BYOM) implementation, ``scorers/static.py`` is a deterministic reference
implementation for tests and demos that need no network/model call at all.

The harness's own job -- everything a scoring library does NOT do -- is
prompt/rubric digest-pinning (``prompt.py``), evidence-ranged recorded claims
as capsules (``capsules.py``), and adjudication sampling (also
``capsules.py``). A ``Scorer`` only ever answers one question: given this
prompt and this evidence, what label (from the prompt's own closed
``label_set``) and how confident.

``JudgeEvidence.evidence_text`` carries plaintext -- deliberately never a
capsule field. The judgment capsule this evidence produces carries only the
evidence RANGE (session id + turn capsule ids + digest), never the content
itself (H2 invariant, same as ``conversation/capsules.py``): the model reads
the content wherever it already lives (the caller's own payload store); the
ledger only ever records that a judgment happened, over what range, with
what result.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .prompt import JudgePromptDefinition

__all__ = ["JudgeEvidence", "ScoreResult", "Scorer"]


@dataclass(frozen=True)
class JudgeEvidence:
    """One evidence range a judge is asked to score.

    ``turn_capsule_ids`` is the append-ordered set of conversation-turn
    capsule ids this judgment is evidenced against (``conversation.capsules``'
    own ``build_turn_capsule`` ids) -- the "evidence range (session digest +
    entry ids)" the B3 task names. ``target_speaker_role`` narrows the
    judgment to one declared speaker role's turns within that range
    (per-speaker sentiment, first-class per the B5 speaker-role shape);
    ``None`` means the judgment targets the whole range.
    """

    session_id: str
    turn_capsule_ids: tuple[str, ...]
    evidence_text: str
    target_speaker_role: str | None = None


@dataclass(frozen=True)
class ScoreResult:
    """One scorer call's result. ``rationale`` is free text (never placed
    raw on a capsule -- ``capsules.py.build_judgment_capsule`` digests it,
    mirroring ``guards/capsule.py``'s ``ConstraintOutcome.evidence`` ->
    ``evidence_digest`` pattern).

    ``model_version`` and ``sampling_params`` feed the judgment capsule's
    full judge pin (``capsules.py``'s ``judge_pin`` block) -- the exact
    model identity and call shape that produced ``label``, so a later re-run
    can be checked against the SAME judge, not just the same ``model_id``
    family. Both are optional (a ``Scorer`` that can't report them, e.g. a
    hosted API with no version string, still produces a valid judgment --
    just a less specific pin). ``sampling_params`` values must be digest-safe
    (int/str/bool only, never a raw float -- same rule ``confidence`` is
    scaled to micros for; a caller with a float param like temperature
    pre-scales it, e.g. ``{"temperature_micros": 700_000}``)."""

    label: str
    confidence: float
    model_id: str
    model_version: str | None = None
    sampling_params: Mapping[str, int | str | bool] | None = None
    rationale: str | None = None


@runtime_checkable
class Scorer(Protocol):
    def score(self, *, evidence: JudgeEvidence, prompt: JudgePromptDefinition) -> ScoreResult: ...
