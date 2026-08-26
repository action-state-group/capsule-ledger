# SPDX-License-Identifier: Apache-2.0
"""Seal the report's own output as a record (build plan Phase 4 item 3:
"Report output sealed as a record (level 3): the report cites the level-2
aggregates it renders"). Design §6c's tower, generalized one level up: a
period report is a record about records, exactly the same shape as a
judgment (level 2) is a record about actions (level 1) -- "no new machinery
per level" (§6c's simplicity discipline).

This capsule is a citation manifest, not a re-statement: it carries the
period, audience, and the full list of capsule ids the report's blocks 1
and 2 rendered (``report.cited_capsule_ids``), never a copy of their
content. A relying party who wants to check the report re-derives the
rendered rows from those cited capsules directly, the same discipline every
other level of this tower already applies.
"""
from __future__ import annotations

from ..guards.capsule import build_event_capsule
from ..guards.signing import Signer
from .model import PeriodReport

__all__ = ["EVENT_PERIOD_REPORT", "seal_period_report_capsule"]

EVENT_PERIOD_REPORT = "capsule_ledger.period_report"


def seal_period_report_capsule(
    report: PeriodReport,
    *,
    operator: str,
    developer: str,
    signer: Signer,
    timestamp: str | None = None,
    action_id: str | None = None,
) -> dict:
    detail = {
        "pack_id": report.pack_id,
        "audience": report.audience,
        "period": {"since": report.since, "until": report.until},
        "cited_capsule_ids": list(report.cited_capsule_ids),
        "row_counts": {
            "coverage": len(report.happened.coverage),
            "not_claimable": len(report.happened.not_claimable),
            "deferrals": len(report.happened.deferrals),
        },
    }
    return build_event_capsule(
        operator=operator,
        developer=developer,
        signer=signer,
        event=EVENT_PERIOD_REPORT,
        detail=detail,
        timestamp=timestamp,
        action_id=action_id or f"capsule_ledger.period_report/{report.pack_id}/{report.since or ''}..{report.until or ''}",
    )
