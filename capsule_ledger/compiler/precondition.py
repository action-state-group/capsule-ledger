# SPDX-License-Identifier: Apache-2.0
"""Precondition vocabulary v0 (design §2.4) -- closed, six primitives:
``cite_record_of_kind``, ``human_approval_of_grade``, ``cap``,
``within_window_of_record``, ``step_order``, ``dedupe_key``.

**What makes re-derivability true is not possession of the plan.** It is a
**published, two-sided conformance vector per primitive** (design §2.4),
verified at registration rather than trusted as submitted -- the same
"registered, not asserted" discipline every other closed vocabulary in this
codebase follows (``vocabulary.py``'s display-string completeness check,
``guards/wickets/definition.py``'s ``KNOWN_CHECKS``).

**Two sides, deliberately asymmetric in what they can see** (mirrors
``guards/checks/plan_containment.py``'s own purity limit): the FORWARD
evaluator is a pure function of ``(primitive, cited_evidence | None)`` -- it
can only confirm a citation matching the primitive's own kind is PRESENT,
never sum/compare/order across a ledger, because forward checks run at act
time with no ledger read (``re_derivability.py``: containment is
``pure_replay``). The BACKWARD evaluator is a pure function of
``(primitive, cited_evidence_set)`` -- a SEALED tuple of evidence records
(what a report-time reader has: everything the citations point at, already
disclosed) -- and it is where the primitive's full semantic lives: summing a
cap, ordering two records, rejecting a duplicate key. A stranger holding
exactly the sealed evidence set the report cites can re-run this function
and get the identical verdict; that reproducibility, not the forward
check's presence-only stub, is what "re-derivable" means for this class of
constraint.

Each primitive's ``citing_label()`` renders into the existing
``guards.plan.PlanPrecondition.citing`` free-text field -- forward
compilation is wiring the closed vocabulary into machinery that already
exists (``guards/checks/plan_containment.py``'s presence check), never a
new forward-check engine.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from agent_action_capsule.canonical import json_digest

from ..folds.duration import parse_duration_seconds
from ..guards.plan import PlanPrecondition

__all__ = [
    "PRECONDITION_KINDS",
    "GRADE_LADDER",
    "InvalidPreconditionParams",
    "EvidenceRecord",
    "PreconditionPrimitive",
    "ConformanceVector",
    "check_forward",
    "check_backward",
    "CONFORMANCE_VECTORS",
    "verify_conformance_vectors",
    "ConformanceViolation",
]

# Closed v0 vocabulary (design §2.4). Token spelling is snake_case for the
# Python-facing ``kind`` field; the design doc's own kebab spelling
# (``cite-record-of-kind-K``) is a prose rendering of the same primitive,
# not a second vocabulary.
PRECONDITION_KINDS = frozenset(
    {
        "cite_record_of_kind",
        "human_approval_of_grade",
        "cap",
        "within_window_of_record",
        "step_order",
        "dedupe_key",
    }
)

# Best-to-worst, for ``human_approval_of_grade``'s "at least as strict as
# required" comparison. Closed for the same "unregistered is a typo" reason
# every other ladder in this codebase is.
GRADE_LADDER = ("A", "B", "C")


class InvalidPreconditionParams(ValueError):
    """A primitive's ``params`` do not match what its ``kind`` requires."""


class ConformanceViolation(ValueError):
    """A registered conformance vector's forward/backward evaluators did not
    agree with the vector's own declared expectation -- raised by
    ``verify_conformance_vectors`` at import time so a primitive that drifts
    from its own published vector fails immediately, not at first use."""


@dataclass(frozen=True)
class EvidenceRecord:
    """One sealed, disclosed evidence item a citation points at -- the
    report-time reader's actual input, deliberately NOT a full ``Capsule``
    (a conformance vector proves the PRIMITIVE's own logic; wiring a real
    capsule's fields through is the fold/loader integration, a later,
    separate task -- see this module's docstring on the forward/backward
    asymmetry)."""

    kind: str
    grade: str | None = None
    amount_minor: int | None = None
    key: str | None = None
    timestamp: str | None = None
    step: int | None = None


@dataclass(frozen=True)
class PreconditionPrimitive:
    kind: str
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in PRECONDITION_KINDS:
            raise InvalidPreconditionParams(f"kind must be one of {sorted(PRECONDITION_KINDS)}; got {self.kind!r}")
        _validate_params(self.kind, self.params)

    def canonical_dict(self) -> dict:
        return {"kind": self.kind, "params": dict(sorted(self.params.items()))}

    def digest(self) -> str:
        return json_digest(self.canonical_dict())

    def citing_label(self) -> str:
        """Renders into ``PlanPrecondition.citing`` -- a short, stable label,
        never a sentence (same "zero free prose" discipline as
        ``compiler.refusal``'s labelled items)."""
        ordered = ",".join(f"{k}={self.params[k]}" for k in sorted(self.params))
        return f"{self.kind}:{ordered}" if ordered else self.kind

    def to_plan_precondition(self, action: str) -> PlanPrecondition:
        """Wiring, not architecture (design §2.1): reuses the existing
        ``guards.plan.PlanPrecondition``/``guards/checks/plan_containment.py``
        presence machinery unchanged -- this primitive only supplies the
        rendered ``citing`` label."""
        return PlanPrecondition(action=action, citing=self.citing_label())


def _validate_params(kind: str, params: dict[str, Any]) -> None:
    if kind == "cite_record_of_kind":
        _require_str(params, "record_kind", kind)
    elif kind == "human_approval_of_grade":
        grade = _require_str(params, "grade", kind)
        if grade not in GRADE_LADDER:
            raise InvalidPreconditionParams(f"{kind}.grade must be one of {GRADE_LADDER}; got {grade!r}")
    elif kind == "cap":
        limit = params.get("limit_minor")
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
            raise InvalidPreconditionParams(f"{kind}.limit_minor must be a non-negative int; got {limit!r}")
    elif kind == "within_window_of_record":
        duration = _require_str(params, "duration", kind)
        try:
            parse_duration_seconds(duration)
        except ValueError as exc:
            raise InvalidPreconditionParams(f"{kind}.duration {duration!r} is not a valid duration: {exc}") from exc
        _require_str(params, "reference_kind", kind)
    elif kind == "step_order":
        _require_str(params, "after_kind", kind)
    elif kind == "dedupe_key":
        _require_str(params, "key_field", kind)
    else:  # pragma: no cover - guarded by __post_init__'s membership check
        raise InvalidPreconditionParams(f"unhandled kind {kind!r}")


def _require_str(params: dict[str, Any], field_name: str, kind: str) -> str:
    value = params.get(field_name)
    if not isinstance(value, str) or not value:
        raise InvalidPreconditionParams(f"{kind}.{field_name} must be a non-empty string; got {value!r}")
    return value


_IDENT_RE = re.compile(r"^[a-z][a-z0-9_]*$")


# --- forward: presence-only, pure, no ledger read ---------------------------


def check_forward(primitive: PreconditionPrimitive, cited: EvidenceRecord | None) -> bool:
    """Mirrors ``guards/checks/plan_containment.py``'s own limit exactly: can
    confirm a citation matching this primitive's kind is present, never sum,
    order, or compare across more than the one cited record."""
    if cited is None:
        return False
    if primitive.kind == "cite_record_of_kind":
        return cited.kind == primitive.params["record_kind"]
    if primitive.kind == "human_approval_of_grade":
        return cited.kind == "human_approval" and cited.grade is not None
    if primitive.kind == "cap":
        return cited.kind == "spend" and cited.amount_minor is not None
    if primitive.kind == "within_window_of_record":
        return cited.kind == "subject" and cited.timestamp is not None
    if primitive.kind == "step_order":
        return cited.kind == "subject" and cited.step is not None
    if primitive.kind == "dedupe_key":
        return cited.kind == "subject" and cited.key is not None
    raise AssertionError(f"unhandled kind {primitive.kind!r}")  # pragma: no cover


# --- backward: re-derived from the full sealed evidence set -----------------


def _grade_at_least(actual: str | None, required: str) -> bool:
    if actual is None or actual not in GRADE_LADDER:
        return False
    return GRADE_LADDER.index(actual) <= GRADE_LADDER.index(required)


def check_backward(primitive: PreconditionPrimitive, evidence: tuple[EvidenceRecord, ...]) -> bool:
    """Re-derives the primitive's verdict from the full sealed evidence set
    a report-time reader actually has -- the direction where each
    primitive's real semantic (sum, order, uniqueness) lives."""
    if primitive.kind == "cite_record_of_kind":
        return any(e.kind == primitive.params["record_kind"] for e in evidence)

    if primitive.kind == "human_approval_of_grade":
        return any(
            e.kind == "human_approval" and _grade_at_least(e.grade, primitive.params["grade"]) for e in evidence
        )

    if primitive.kind == "cap":
        total = sum(e.amount_minor for e in evidence if e.kind == "spend" and e.amount_minor is not None)
        return total <= primitive.params["limit_minor"]

    if primitive.kind == "within_window_of_record":
        window_seconds = parse_duration_seconds(primitive.params["duration"])
        reference = next((e for e in evidence if e.kind == primitive.params["reference_kind"]), None)
        if reference is None or reference.timestamp is None:
            return False
        ref_seconds = _parse_iso_seconds(reference.timestamp)
        subjects = [e for e in evidence if e.kind == "subject" and e.timestamp is not None]
        if not subjects:
            return False
        return all(abs(_parse_iso_seconds(e.timestamp) - ref_seconds) <= window_seconds for e in subjects)

    if primitive.kind == "step_order":
        predecessor = next((e for e in evidence if e.kind == primitive.params["after_kind"]), None)
        subject = next((e for e in evidence if e.kind == "subject"), None)
        if predecessor is None or subject is None or predecessor.step is None or subject.step is None:
            return False
        return predecessor.step < subject.step

    if primitive.kind == "dedupe_key":
        keys = [e.key for e in evidence if e.kind == "subject" and e.key is not None]
        return len(keys) == len(set(keys)) and len(keys) > 0

    raise AssertionError(f"unhandled kind {primitive.kind!r}")  # pragma: no cover


def _parse_iso_seconds(value: str) -> int:
    from datetime import datetime, timezone

    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


# --- published, two-sided conformance vectors --------------------------------


@dataclass(frozen=True)
class ConformanceVector:
    """One published scenario for one primitive, exercised through BOTH
    evaluators. ``forward_citation`` is the single record a forward check
    would see; ``evidence`` is the full sealed set a backward check would
    see -- normally ``(forward_citation,) + more`` (backward can see
    everything forward could, plus what forward's purity kept it from
    reading)."""

    kind: str
    scenario: str
    forward_citation: EvidenceRecord | None
    evidence: tuple[EvidenceRecord, ...]
    expect_forward: bool
    expect_backward: bool


CONFORMANCE_VECTORS: tuple[ConformanceVector, ...] = (
    # -- cite_record_of_kind -------------------------------------------------
    ConformanceVector(
        kind="cite_record_of_kind",
        scenario="incident_ticket_cited",
        forward_citation=EvidenceRecord(kind="incident_ticket"),
        evidence=(EvidenceRecord(kind="incident_ticket"),),
        expect_forward=True,
        expect_backward=True,
    ),
    ConformanceVector(
        kind="cite_record_of_kind",
        scenario="wrong_kind_cited",
        forward_citation=EvidenceRecord(kind="spend"),
        evidence=(EvidenceRecord(kind="spend"),),
        expect_forward=False,
        expect_backward=False,
    ),
    # -- human_approval_of_grade ---------------------------------------------
    ConformanceVector(
        kind="human_approval_of_grade",
        scenario="grade_a_approval_meets_grade_b_requirement",
        forward_citation=EvidenceRecord(kind="human_approval", grade="A"),
        evidence=(EvidenceRecord(kind="human_approval", grade="A"),),
        expect_forward=True,
        expect_backward=True,
    ),
    ConformanceVector(
        kind="human_approval_of_grade",
        scenario="grade_c_approval_fails_grade_b_requirement",
        forward_citation=EvidenceRecord(kind="human_approval", grade="C"),
        evidence=(EvidenceRecord(kind="human_approval", grade="C"),),
        expect_forward=True,  # forward is presence-only: it cannot see the grade shortfall
        expect_backward=False,
    ),
    # -- cap ------------------------------------------------------------------
    ConformanceVector(
        kind="cap",
        scenario="under_the_limit",
        forward_citation=EvidenceRecord(kind="spend", amount_minor=100),
        evidence=(EvidenceRecord(kind="spend", amount_minor=100), EvidenceRecord(kind="spend", amount_minor=200)),
        expect_forward=True,
        expect_backward=True,
    ),
    ConformanceVector(
        kind="cap",
        scenario="over_the_limit_across_records",
        forward_citation=EvidenceRecord(kind="spend", amount_minor=100),
        evidence=(EvidenceRecord(kind="spend", amount_minor=600), EvidenceRecord(kind="spend", amount_minor=600)),
        expect_forward=True,  # forward cannot sum across records, only see one citation present
        expect_backward=False,
    ),
    # -- within_window_of_record ----------------------------------------------
    ConformanceVector(
        kind="within_window_of_record",
        scenario="subject_inside_window",
        forward_citation=EvidenceRecord(kind="subject", timestamp="2026-08-19T12:00:00Z"),
        evidence=(
            EvidenceRecord(kind="incident_ticket", timestamp="2026-08-19T10:00:00Z"),
            EvidenceRecord(kind="subject", timestamp="2026-08-19T12:00:00Z"),
        ),
        expect_forward=True,
        expect_backward=True,
    ),
    ConformanceVector(
        kind="within_window_of_record",
        scenario="subject_outside_window",
        forward_citation=EvidenceRecord(kind="subject", timestamp="2026-09-02T12:00:00Z"),
        evidence=(
            EvidenceRecord(kind="incident_ticket", timestamp="2026-08-19T10:00:00Z"),
            EvidenceRecord(kind="subject", timestamp="2026-09-02T12:00:00Z"),
        ),
        expect_forward=True,  # forward cannot see the reference record's timestamp at all
        expect_backward=False,
    ),
    # -- step_order -------------------------------------------------------------
    ConformanceVector(
        kind="step_order",
        scenario="approval_precedes_dispatch",
        forward_citation=EvidenceRecord(kind="subject", step=2),
        evidence=(EvidenceRecord(kind="human_approval", step=1), EvidenceRecord(kind="subject", step=2)),
        expect_forward=True,
        expect_backward=True,
    ),
    ConformanceVector(
        kind="step_order",
        scenario="approval_follows_dispatch",
        forward_citation=EvidenceRecord(kind="subject", step=1),
        evidence=(EvidenceRecord(kind="human_approval", step=2), EvidenceRecord(kind="subject", step=1)),
        expect_forward=True,  # forward cannot see the predecessor's own step index
        expect_backward=False,
    ),
    # -- dedupe_key ---------------------------------------------------------------
    ConformanceVector(
        kind="dedupe_key",
        scenario="unique_key",
        forward_citation=EvidenceRecord(kind="subject", key="order-1"),
        evidence=(EvidenceRecord(kind="subject", key="order-1"),),
        expect_forward=True,
        expect_backward=True,
    ),
    ConformanceVector(
        kind="dedupe_key",
        scenario="duplicate_key_across_records",
        forward_citation=EvidenceRecord(kind="subject", key="order-1"),
        evidence=(EvidenceRecord(kind="subject", key="order-1"), EvidenceRecord(kind="subject", key="order-1")),
        expect_forward=True,  # forward only ever sees the one citation being dispatched, never the rest
        expect_backward=False,
    ),
)

_DEFAULT_PARAMS: dict[str, dict[str, Any]] = {
    "cite_record_of_kind": {"record_kind": "incident_ticket"},
    "human_approval_of_grade": {"grade": "B"},
    "cap": {"limit_minor": 500},
    "within_window_of_record": {"duration": "7d", "reference_kind": "incident_ticket"},
    "step_order": {"after_kind": "human_approval"},
    "dedupe_key": {"key_field": "order_id"},
}


def verify_conformance_vectors(
    vectors: tuple[ConformanceVector, ...] | None = None,
) -> list[str]:
    """Run every vector (defaults to the real, published ``CONFORMANCE_VECTORS``)
    through both evaluators and return a description of every mismatch found.
    Empty means every primitive's forward/backward pair agrees with its own
    published expectation. Used both as the import-time gate and, with a
    deliberately corrupted ``vectors`` argument, as the RED-before-green
    mutant proof that this check can fail at all."""
    violations: list[str] = []
    seen_kinds: set[str] = set()
    for v in vectors if vectors is not None else CONFORMANCE_VECTORS:
        seen_kinds.add(v.kind)
        primitive = PreconditionPrimitive(kind=v.kind, params=_DEFAULT_PARAMS[v.kind])
        actual_forward = check_forward(primitive, v.forward_citation)
        actual_backward = check_backward(primitive, v.evidence)
        if actual_forward != v.expect_forward:
            violations.append(
                f"{v.kind}/{v.scenario}: forward evaluator returned {actual_forward}, vector expects {v.expect_forward}"
            )
        if actual_backward != v.expect_backward:
            violations.append(
                f"{v.kind}/{v.scenario}: backward evaluator returned {actual_backward}, "
                f"vector expects {v.expect_backward}"
            )
    missing = sorted(PRECONDITION_KINDS - seen_kinds)
    if missing:
        violations.append(f"no published conformance vector for {missing}")
    return violations


def assert_conformance_vectors_hold() -> None:
    violations = verify_conformance_vectors()
    if violations:
        raise ConformanceViolation("; ".join(violations))


assert_conformance_vectors_hold()
