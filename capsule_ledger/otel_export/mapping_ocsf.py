# SPDX-License-Identifier: Apache-2.0
"""OCSF mapping -- SECONDARY export target, best-effort only.

**There is no ratified OCSF event class for AI-agent activity, tool calls,
or AI-governance findings** (verified against schema.ocsf.io/1.3.0; Exabeam
worked around the same gap with a private CIM extension rather than a
standard OCSF class). This package does not block on that gap -- OTLP/
``gen_ai`` (``mapping_genai.py``) is the primary target and works today; this
module maps onto the *closest existing* class and says so honestly, per the
task that created this module rather than pretending a first-class fit
exists.

**Chosen class: Detection Finding (class_uid 2004, category "Findings",
category_uid 2).** Its ``disposition_id`` is the only OCSF-standard field
that carries an allow/block-shaped outcome (``1``=Allowed, ``2``=Blocked --
the schema's own words: "the outcome or action taken by a security
control"), which is the closest existing counterpart to this package's own
``ALLOW``/``DENY`` decisions.

**The mismatch, stated honestly:** Detection Finding models a security
product's detection of malware/anomalies/policy violations, not a real-time
gate on an AI agent's proposed action -- the class's own semantics assume a
detection *about* something that already happened, where a mediated-action
decision is a gate applied *before* dispatch. Its ``disposition_id`` enum
has no value for "routed to a human, awaiting resolution" (this package's
``STEP_UP``), a human-elected postponement (``DEFER``), or an in-flight
action altered before dispatch (``MODIFY``) -- all three fall back to
``99`` (``Other``), which is a real loss of fidelity a verifier reading only
the OCSF projection would not recover without the ``asg_ext`` unmapped bag
below. This is exactly why the profile document (`agent-action-capsule`)
states the telemetry event -- in any mapping -- is not evidence: this
mapping's own gaps are a demonstration of the point, not just a disclaimer
about it.

Follow-up (ticketed, not built here): propose an OCSF activity class for
mediated agent actions -- see the ledger-lane outbox for this task.
"""
from __future__ import annotations

from .event import ALLOW, DEFER, DENY, MODIFY, STEP_UP, DecisionEvent

__all__ = ["OCSF_CLASS_UID", "OCSF_CATEGORY_UID", "to_ocsf_finding"]

OCSF_CLASS_UID = 2004  # Detection Finding
OCSF_CLASS_NAME = "Detection Finding"
OCSF_CATEGORY_UID = 2  # Findings
OCSF_CATEGORY_NAME = "Findings"
OCSF_ACTIVITY_ID = 1  # "Create" -- each decision is a new finding, never updated/closed in place
OCSF_ACTIVITY_NAME = "Create"

_DISPOSITION_BY_DECISION = {
    ALLOW: (1, "Allowed"),
    DENY: (2, "Blocked"),
    STEP_UP: (99, "Other"),  # no "routed to human, awaiting resolution" value exists
    DEFER: (99, "Other"),  # no human-elected-postponement value exists
    MODIFY: (99, "Other"),  # no in-flight-action-altered value exists
}


def to_ocsf_finding(event: DecisionEvent) -> dict:
    """Best-effort OCSF Detection Finding shape. This package's own
    attribute set (receipt/manifest/plan digests, containment result,
    identity facets) has no home in the standard OCSF schema for this
    class, so it rides in ``unmapped`` -- OCSF's own escape hatch for
    "additional data source attributes that do not map to the schema" --
    under an ``asg_ext`` prefix, so nothing is lost to the projection even
    though the standard fields alone would lose fidelity (see module
    docstring)."""
    disposition_id, disposition = _DISPOSITION_BY_DECISION[event.decision]
    return {
        "class_uid": OCSF_CLASS_UID,
        "class_name": OCSF_CLASS_NAME,
        "category_uid": OCSF_CATEGORY_UID,
        "category_name": OCSF_CATEGORY_NAME,
        "activity_id": OCSF_ACTIVITY_ID,
        "activity_name": OCSF_ACTIVITY_NAME,
        "disposition_id": disposition_id,
        "disposition": disposition,
        "unmapped": {f"asg_ext.{k}": v for k, v in event.to_attributes().items()},
    }
