# SPDX-License-Identifier: Apache-2.0
"""The fourth verdict state (backward-judge design §11): **insufficient
evidence**, the honest negative case a two-value pass/fail schema cannot
express -- *"we cannot tell whether it happened, because the evidence it
needs was never emitted."* Distinct from a real ``fail`` (evidence present,
outcome not met) and never allowed to collapse into one:

- **held** (``pass``) -- evidence present, outcome met.
- **failed** (``fail``) -- evidence present, outcome not met.
- **insufficient_evidence** -- evidence absent; the verdict names the
  missing field/capsule-shape (§11: *"the verdict names the missing
  field"*), never a fail, never laundered into a pass.

This module is the judge-side gate: given a term's declared
``EvidenceRequirement``s and the evidence bundle actually available for a
session, ``resolve_verdict`` decides *before* any scoring happens whether
there is enough evidence to judge at all. When there isn't, the real
scorer/judge callback is never invoked -- the missing-evidence path is a
structural gate, not a post-hoc relabelling of a judgment that already ran.

``INSUFFICIENT_EVIDENCE`` is a new top-level ``verdict`` value (design §11's
own framing: *"verdict = insufficient_evidence"*), not a sub-reason of the
codebase's existing ``ABSTAIN``/``abstain_reason`` shape (``abstain_reason``
already carries an ``"insufficient_evidence"`` value, but as one of three
reasons a judge that *ran* couldn't produce a verdict -- see
``capsule_compiler.judge_agent.payload.VerdictPayload``; ABSTAIN's reasons
never name a field). ``missing_evidence`` here is the field/capsule-shape
name itself, e.g. ``"read_observation.chain_parent_digest"`` -- specific
enough that the report can tell an operator exactly what to emit to make
the term judgeable (§12: "emit both sides").
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from ..folds.paths import ABSENT, get_path
from .errors import MISSING_EVIDENCE_LABEL_NOT_ALLOWED, MISSING_EVIDENCE_LABEL_REQUIRED, JudgeError

__all__ = [
    "INSUFFICIENT_EVIDENCE",
    "EvidenceRequirement",
    "first_missing_requirement",
    "resolve_verdict",
    "verdict_detail",
]

INSUFFICIENT_EVIDENCE = "insufficient_evidence"


@dataclass(frozen=True)
class EvidenceRequirement:
    """One field a term's ``evidence_rule`` needs present on the session's
    evidence bundle before a verdict can be judged at all. ``path`` is a
    dotted lookup key into that bundle (``folds.paths.get_path`` semantics
    -- missing at any level counts as absent; a key present with an
    explicit ``null`` also counts as absent, since a null evidence value is
    exactly as unusable as a missing one). ``label`` is what the report
    names as the missing field/capsule-shape (design §11) -- defaults to
    ``path`` when the wire path and the human-readable name are the same
    thing."""

    path: str
    label: str | None = None

    @property
    def display_label(self) -> str:
        return self.label if self.label is not None else self.path


def first_missing_requirement(
    requirements: Sequence[EvidenceRequirement], evidence: Mapping
) -> EvidenceRequirement | None:
    """The first requirement ``evidence`` does not satisfy, in declared
    order, or ``None`` if every requirement is met. First-missing wins
    (design §11: "the verdict names *the* missing field", singular) --
    ``requirements`` should be ordered most-fundamental-first when a term
    has more than one."""
    for requirement in requirements:
        value = get_path(dict(evidence), requirement.path, ABSENT)
        if value is ABSENT or value is None:
            return requirement
    return None


def resolve_verdict(
    requirements: Sequence[EvidenceRequirement],
    evidence: Mapping,
    *,
    judge: Callable[[], str],
) -> tuple[str, str | None]:
    """The gate: check evidence completeness first, and only ever call
    ``judge`` (the real scorer/rule -- whatever produces a ``pass``/``fail``
    style verdict) when every requirement is met. Returns
    ``(verdict, missing_evidence)`` -- ``missing_evidence`` is ``None``
    unless ``verdict == INSUFFICIENT_EVIDENCE``. This is what makes "never
    render as fail" structural rather than a convention to remember: when
    evidence is missing, ``judge`` is simply never invoked, so it cannot
    produce a fail (or a pass) for a session that was never judgeable."""
    missing = first_missing_requirement(requirements, evidence)
    if missing is not None:
        return INSUFFICIENT_EVIDENCE, missing.display_label
    return judge(), None


def verdict_detail(
    *,
    subject: Mapping,
    term_id: str,
    c_digest: str,
    epoch: str,
    applicable: bool,
    verdict: str,
    missing_evidence: str | None = None,
) -> dict:
    """The ``asg_payload.detail`` shape a ``judge_agent_verdict`` capsule
    seals (mirrors ``examples.tau2_pack_outcomes_walkthrough.
    seal_sampled_verdicts``'s inline dict / ``capsule_compiler.judge_agent.
    payload.VerdictPayload.to_detail``'s wire shape, plus the new
    ``missing_evidence`` field). Validates the same way ``VerdictPayload``
    validates ``abstain_reason``: required iff the verdict is
    ``insufficient_evidence``, forbidden otherwise -- a non-insufficient row
    silently carrying a missing-evidence label would be exactly the kind of
    ambiguity this state exists to close."""
    if verdict == INSUFFICIENT_EVIDENCE:
        if not missing_evidence:
            raise JudgeError(
                MISSING_EVIDENCE_LABEL_REQUIRED,
                "verdict == 'insufficient_evidence' requires a non-empty missing_evidence label",
            )
    elif missing_evidence is not None:
        raise JudgeError(
            MISSING_EVIDENCE_LABEL_NOT_ALLOWED,
            f"missing_evidence is only valid when verdict == {INSUFFICIENT_EVIDENCE!r}; got verdict={verdict!r}",
        )
    return {
        "subject": dict(subject),
        "term": {"term_id": term_id, "c_digest": c_digest},
        "epoch": epoch,
        "applicable": applicable,
        "verdict": verdict,
        "missing_evidence": missing_evidence,
    }
