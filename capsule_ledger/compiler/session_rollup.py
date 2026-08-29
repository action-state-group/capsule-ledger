# SPDX-License-Identifier: Apache-2.0
"""The per-session ``insufficient_evidence`` rollup (backward-judge design
§11/§8.4): *"a session with any applicable [term] in insufficient_evidence
is not a successful job -- but it goes in a third list, 'unprovable,'
separate from near-miss (which is a real failed)."*

This module builds the classification primitive that third list needs:
group applicable ``judge_agent_verdict`` rows by session (``detail.
subject``) and, per session, decide whether it has a real failure
(``near_miss``) or is merely unprovable (every problem it has is a missing
evidence field, never a failed outcome). **Scope note:** the full §8.4 job
rollup additionally gates on a term's ``tier`` (``must_have`` vs
``informational``, ``[ldg-bj-tier-field]``) and renders the positive
"successful jobs" list -- that field does not exist on ``Outcome``/
``TermDeclaration`` yet, so this module classifies over every *applicable*
term present in ``records``, not only a pack's declared must-haves. Wiring
tier-scoped gating and the "successful" list is ``[ldg-bj-session-report-
respine]``'s job; this module is the grouping primitive it builds on.

Same "plain iteration for structural discovery, never a hand-rolled count"
convention ``terms_report._verdict_partitions`` already uses -- there is no
number to compute here (no COUNT goes through the fold engine), only a
classification per session, so plain iteration is the right tool, not a
second fold engine.
"""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..judge.evidence_completeness import INSUFFICIENT_EVIDENCE
from .terms_report import EVENT_SATELLITE_VERDICT

__all__ = ["FailedTerm", "UnprovableTerm", "SessionRollupRow", "rollup_unprovable_sessions"]

_FAIL_VERDICT = "fail"


@dataclass(frozen=True)
class FailedTerm:
    term_id: str

    def to_dict(self) -> dict:
        return {"term_id": self.term_id}


@dataclass(frozen=True)
class UnprovableTerm:
    """One term this session cannot be judged on -- ``missing_evidence`` is
    the exact field/capsule-shape name the report surfaces (design §11:
    "the report ... names, per session, exactly which field to emit to
    make it judgeable")."""

    term_id: str
    missing_evidence: str

    def to_dict(self) -> dict:
        return {"term_id": self.term_id, "missing_evidence": self.missing_evidence}


@dataclass(frozen=True)
class SessionRollupRow:
    """One session's classification. ``status`` is ``near_miss`` when the
    session has at least one applicable real failure (a true ``fail`` --
    evidence present, outcome not met), ``unprovable`` when it has no
    failure but at least one applicable term is ``insufficient_evidence``,
    or ``clean`` when this rollup saw neither for this session (such
    sessions are never actually returned by ``rollup_unprovable_sessions``
    below -- this module surfaces only the near-miss/unprovable lists, not
    the positive "successful" list). ``near_miss`` takes precedence over
    ``unprovable`` -- design §11's "separate from near-miss (which is a
    real failed)" reads as near-miss being the more specific, more
    actionable finding when a session has both a real failure and an
    unrelated evidence gap."""

    subject: Mapping[str, Any]
    failed_terms: tuple[FailedTerm, ...]
    unprovable_terms: tuple[UnprovableTerm, ...]

    @property
    def status(self) -> str:
        if self.failed_terms:
            return "near_miss"
        if self.unprovable_terms:
            return "unprovable"
        return "clean"

    def to_dict(self) -> dict:
        return {
            "subject": dict(self.subject),
            "status": self.status,
            "failed_terms": [t.to_dict() for t in self.failed_terms],
            "unprovable_terms": [t.to_dict() for t in self.unprovable_terms],
        }


def _subject_key(subject: Mapping[str, Any]) -> str:
    """A stable, hashable stand-in for a session's ``subject`` dict --
    ``subject``'s own shape is not yet standardized across call sites (the
    tau2 walkthrough uses ``{sim_id, task_id}``; ``VerdictPayload`` uses
    ``{capsule_id, digest}``; design §8.4 itself notes the session-id field
    is still "whichever ... the outcome-compiler wiring settles on") -- so
    this groups structurally by the subject's own canonical JSON rather
    than assuming any one field name."""
    return json.dumps(subject, sort_keys=True)


def rollup_unprovable_sessions(records: Sequence[dict]) -> tuple[SessionRollupRow, ...]:
    """Group every applicable ``judge_agent_verdict`` row by session and
    classify it near_miss / unprovable / clean. Returns only the near_miss
    and unprovable rows, in first-seen order -- a session with nothing but
    ``pass``/held verdicts has nothing this rollup reports, by design (the
    positive "successful jobs" list is §8.4's job, not this module's)."""
    by_subject: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for record in records:
        payload = record.get("asg_payload") or {}
        if payload.get("event") != EVENT_SATELLITE_VERDICT:
            continue
        detail = payload.get("detail") or {}
        if not detail.get("applicable", False):
            continue
        subject = detail.get("subject")
        if not isinstance(subject, Mapping):
            continue
        term = detail.get("term") or {}
        term_id = term.get("term_id")
        verdict = detail.get("verdict")
        if verdict not in (_FAIL_VERDICT, INSUFFICIENT_EVIDENCE):
            continue

        key = _subject_key(subject)
        if key not in by_subject:
            by_subject[key] = {"subject": subject, "failed": [], "unprovable": []}
            order.append(key)
        bucket = by_subject[key]
        if verdict == _FAIL_VERDICT:
            bucket["failed"].append(FailedTerm(term_id=term_id))
        else:
            missing = detail.get("missing_evidence") or "(unnamed field -- judge sealed insufficient_evidence without naming what was missing)"
            bucket["unprovable"].append(UnprovableTerm(term_id=term_id, missing_evidence=missing))

    rows: list[SessionRollupRow] = []
    for key in order:
        bucket = by_subject[key]
        rows.append(
            SessionRollupRow(
                subject=bucket["subject"],
                failed_terms=tuple(bucket["failed"]),
                unprovable_terms=tuple(bucket["unprovable"]),
            )
        )
    return tuple(rows)
