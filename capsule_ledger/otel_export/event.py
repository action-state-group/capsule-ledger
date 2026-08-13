# SPDX-License-Identifier: Apache-2.0
"""``DecisionEvent``: the producer-neutral shape every ``otel_export`` mapping
module and the exporter itself consume. Decoupled from ``GuardEngine``/
``GuardDecision`` so the mapping/export code can be built and tested without a
live engine, and so a future non-guard producer (a hold decision, a pack
enforcement point) can feed the same pipe.

**The design rule this whole package exists to enforce (ldg-otel-exporter-
aarm-r8): the event carries a receipt REFERENCE, never a receipt COPY.**
``receipt_digest`` is a required field with no default -- a ``DecisionEvent``
that has nothing to point at cannot be constructed, which is what makes
"receipt digest present on every emitted event" a property of the type, not a
promise about how callers happen to use it (same move as
``telemetry/events.py``'s ``MetricEvent``). There is deliberately no field
here that could carry a capsule payload, a constraint's evidence, or any
other receipt content -- only identifiers and the decision itself.

``plan_digest``/``containment_result`` are optional and absent-when-
unavailable, same pattern as ``guards/capsule.py``'s ``manifest_digest``:
they come from ``[ldg-plan-containment]``'s C1/C2 artifacts, a separate
in-progress branch not yet on ``main`` at the time this was written.

``identity_*`` are explicit optional pass-through fields, not auto-derived
from ``Action.operator``/``Action.developer`` -- this codebase's own
docstrings and examples use those two fields loosely (an org-ish caller
context and an agent/service label) and neither maps cleanly onto all four
AARM identity facets, so guessing a mapping here would assert semantics this
codebase doesn't actually have. Callers who know their own auth context pass
the facets that apply; the rest stay absent.
"""
from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "ALLOW",
    "DENY",
    "MODIFY",
    "STEP_UP",
    "DEFER",
    "DECISION_VALUES",
    "DecisionEvent",
    "decision_event_from_guard_decision",
]

ALLOW = "ALLOW"
DENY = "DENY"
MODIFY = "MODIFY"
STEP_UP = "STEP_UP"
DEFER = "DEFER"
DECISION_VALUES = frozenset({ALLOW, DENY, MODIFY, STEP_UP, DEFER})

# GuardEngine's own outcome vocabulary (guards/capsule.py: allow|deny|escalate)
# mapped onto the AARM R8 decision vocabulary. `escalate` -> STEP_UP, not
# DEFER: `escalate` routes to a human who has not yet acted (matches
# guards/capsule.py's own hitl_dispatched mapping for the same outcome);
# DEFER is a *human*-elected postponement, a different, later state that this
# guard has no path to produce. `MODIFY` is not emitted by GuardEngine today
# either -- both are here for producers this event shape doesn't yet have.
_OUTCOME_TO_DECISION = {"allow": ALLOW, "deny": DENY, "escalate": STEP_UP}


@dataclass(frozen=True)
class DecisionEvent:
    """One mediated-action decision, shaped for export. Never holds a
    receipt payload -- only the pointer to it."""

    action_verb: str
    decision: str
    receipt_digest: str
    action_target: str | None = None
    manifest_digest: str | None = None
    plan_digest: str | None = None
    outcome_id: str | None = None
    plan_step_index: int | None = None
    containment_result: str | None = None
    identity_human: str | None = None
    identity_service: str | None = None
    identity_agent: str | None = None
    identity_session: str | None = None

    def __post_init__(self) -> None:
        if not self.receipt_digest:
            raise ValueError("DecisionEvent.receipt_digest is required -- a telemetry event with nothing to point at is not a pointer")
        if self.decision not in DECISION_VALUES:
            raise ValueError(f"decision must be one of {sorted(DECISION_VALUES)}, got {self.decision!r}")
        if self.containment_result is not None and self.containment_result not in {"pass", "fail"}:
            raise ValueError(f"containment_result must be 'pass' or 'fail', got {self.containment_result!r}")

    def to_attributes(self) -> dict[str, str | int]:
        """The minimum attribute set, dotted-namespaced per the acceptance
        list, optional fields included only when present -- same pattern as
        ``guards/capsule.py``'s ``asg_payload`` extension fields."""
        attrs: dict[str, str | int] = {
            "action.verb": self.action_verb,
            "decision": self.decision,
            "receipt.digest": self.receipt_digest,
        }
        optional = {
            "action.target": self.action_target,
            "manifest.digest": self.manifest_digest,
            "plan.digest": self.plan_digest,
            "outcome.id": self.outcome_id,
            "plan.step_index": self.plan_step_index,
            "containment.result": self.containment_result,
            "identity.human": self.identity_human,
            "identity.service": self.identity_service,
            "identity.agent": self.identity_agent,
            "identity.session": self.identity_session,
        }
        for key, value in optional.items():
            if value is not None:
                attrs[key] = value
        return attrs


def decision_event_from_guard_decision(
    decision,
    action,
    *,
    plan_digest: str | None = None,
    outcome_id: str | None = None,
    plan_step_index: int | None = None,
    containment_result: str | None = None,
    identity_human: str | None = None,
    identity_service: str | None = None,
    identity_agent: str | None = None,
    identity_session: str | None = None,
) -> DecisionEvent | None:
    """Build a ``DecisionEvent`` from a ``guards.GuardDecision`` + the
    ``Action`` it decided. Returns ``None`` when ``decision.capsule`` is
    ``None`` (the guard's own fail-closed paths that mint no capsule at all
    -- signing-key-unavailable, view-unhealthy) -- there is no receipt to
    reference yet, and a ``DecisionEvent`` cannot fabricate one. Callers
    should treat ``None`` as "nothing to export for this decision", not an
    error.
    """
    if decision.capsule is None:
        return None
    mapped = _OUTCOME_TO_DECISION.get(decision.outcome)
    if mapped is None:
        raise ValueError(f"unmapped GuardDecision.outcome {decision.outcome!r}")
    payload = decision.capsule.get("asg_payload") or {}
    return DecisionEvent(
        action_verb=action.verb,
        decision=mapped,
        receipt_digest=decision.capsule["capsule_id"],
        action_target=action.target,
        manifest_digest=payload.get("manifest_digest"),
        plan_digest=plan_digest,
        outcome_id=outcome_id,
        plan_step_index=plan_step_index,
        containment_result=containment_result,
        identity_human=identity_human,
        identity_service=identity_service,
        identity_agent=identity_agent,
        identity_session=identity_session,
    )
