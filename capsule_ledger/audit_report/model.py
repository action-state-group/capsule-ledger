# SPDX-License-Identifier: Apache-2.0
"""Data shapes for the three blocks design §3.6 specifies, in order: what was
promised, what happened, can I check it. Every field here is either read
straight off a sealed capsule or computed from one -- ``collect.py`` is
where each field comes from; this module only carries the shape.
"""
from __future__ import annotations

from dataclasses import dataclass, field

__all__ = [
    "AUDIENCES",
    "SuppressionProfile",
    "suppression_profile_for",
    "WhatWasPromisedBlock",
    "OutcomeCoverageRow",
    "NotClaimableRow",
    "DeferralRow",
    "WhatHappenedBlock",
    "VerifyRow",
    "PeriodReport",
]

AUDIENCES = frozenset({"internal", "counterparty", "auditor"})


@dataclass(frozen=True)
class SuppressionProfile:
    """A bundle-profile function of audience (design §3.6: "audience is a
    report parameter and suppression is a bundle-profile function of it --
    that is what makes the audience and suppression questions one mechanism
    instead of two"). **Default suppression OFF for every audience** -- the
    parameter is built now; the flip to redacting fields for
    ``counterparty``/``auditor`` waits on gate G-SUPP (build plan gate
    table: an open, unanswered question this repo does not design around a
    guess for). Every field below is therefore ``False`` for all three
    audiences today; this dataclass exists so the flip is a one-line change
    to ``suppression_profile_for``, not a new mechanism.
    """

    redact_operator: bool = False
    redact_developer: bool = False


def suppression_profile_for(audience: str) -> SuppressionProfile:
    if audience not in AUDIENCES:
        raise ValueError(f"audience must be one of {sorted(AUDIENCES)}; got {audience!r}")
    return SuppressionProfile()


@dataclass(frozen=True)
class WhatWasPromisedBlock:
    """Block 1 (design §3.6 item 1): the accepted declarations (T1) and the
    scope census (T2), with freshness. Any field may be ``None`` when the
    corresponding capsule was never found in the period -- rendered
    honestly as "not recorded", never silently omitted."""

    document_digest: str | None
    census_n: int | None
    census_m: int | None
    census_review_by: str | None
    census_capsule_id: str | None
    d_digest: str | None
    c_digest: str | None
    p_digest: str | None
    f_digest: str | None
    compiler_id: str | None
    compiler_version: str | None
    acceptance_capsule_id: str | None
    accepted_by: str | None


@dataclass(frozen=True)
class OutcomeCoverageRow:
    """One row of the two-column "Enforced by" / "Evidenced by" table
    (design §3.6 item 2) -- the verdict pair (design §2.2) made visible.
    ``n``/``m`` are a denominator, never a bare percentage (design §3.4)."""

    outcome_id: str
    statement: str
    forward_verdict: str
    forward_display: str
    backward_verdict: str
    backward_display: str
    n: int
    m: int
    evidenced_capsule_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class NotClaimableRow:
    """One row of the not-claimable register (design §3.6 item 2:
    "refusals and WITH-INSTRUMENTATION items rendered as a 'not claimable'
    register ... T4's acknowledgment signs this register"). ``acknowledged``
    is True only when a real T4 capsule chained to ``refusal_capsule_id``
    was found -- an unacknowledged refusal is rendered as such, not hidden."""

    outcome_id: str
    statement: str
    reason_category: str  # "refused" | "with_instrumentation"
    reason_display: str
    refusal_capsule_id: str | None
    acknowledged: bool
    acknowledgment_capsule_id: str | None


@dataclass(frozen=True)
class DeferralRow:
    """One entry in the deferral/shadow-queue aging list (design §3.6 item
    2: "the kelly lesson: a deferral rotting invisibly is the failure mode;
    the report is where it becomes visible"). ``age_label`` is rendered
    ("14d"), never a bare timestamp -- aging is the whole point of the row."""

    offer_id: str
    response_capsule_id: str
    offered_at: str
    age_label: str


@dataclass(frozen=True)
class WhatHappenedBlock:
    coverage: tuple[OutcomeCoverageRow, ...] = ()
    not_claimable: tuple[NotClaimableRow, ...] = ()
    deferrals: tuple[DeferralRow, ...] = ()


@dataclass(frozen=True)
class VerifyRow:
    """Block 3 (design §3.6 item 3): one row resolves to a capsule id an
    auditor can check offline. ``label`` is a short, honest tag for where
    this capsule came from (e.g. "census", "outcome.refund_confirmed ·
    response"), never free prose. The verify *command* itself is rendered
    at render time (``render.py``), once the report's own bundle path is
    known -- this row only carries what it cites."""

    label: str
    capsule_id: str


@dataclass(frozen=True)
class PeriodReport:
    pack_id: str
    audience: str
    since: str | None
    until: str | None
    generated_at: str
    promised: WhatWasPromisedBlock
    happened: WhatHappenedBlock
    verify_rows: tuple[VerifyRow, ...] = ()
    bundle_path: str | None = None
    report_capsule_id: str | None = None
    cited_capsule_ids: tuple[str, ...] = field(default_factory=tuple)

    def with_seal(self, *, report_capsule_id: str, bundle_path: str) -> PeriodReport:
        import dataclasses

        return dataclasses.replace(self, report_capsule_id=report_capsule_id, bundle_path=bundle_path)
