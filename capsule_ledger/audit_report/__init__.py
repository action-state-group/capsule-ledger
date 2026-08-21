# SPDX-License-Identifier: Apache-2.0
"""``capsule report`` -- design §3.6, the buyer's front door.

Not to be confused with ``capsule_ledger.report`` (the guard dry-run /
replay-before-merge report, design §3.5) -- a different verb answering a
different question ("what would this policy change have held") for a
different audience (the developer merging a PR). This package is the
period, audience-scoped, three-block record a GRC member opens monthly and
an auditor opens annually. Named ``audit_report`` rather than reusing
``report`` specifically so the two are never confused in an import line.
"""
from __future__ import annotations

from .collect import build_period_report
from .model import (
    NotClaimableRow,
    OutcomeCoverageRow,
    PeriodReport,
    VerifyRow,
    WhatHappenedBlock,
    WhatWasPromisedBlock,
)
from .render import render_text
from .seal import EVENT_PERIOD_REPORT, seal_period_report_capsule

__all__ = [
    "EVENT_PERIOD_REPORT",
    "NotClaimableRow",
    "OutcomeCoverageRow",
    "PeriodReport",
    "VerifyRow",
    "WhatHappenedBlock",
    "WhatWasPromisedBlock",
    "build_period_report",
    "render_text",
    "seal_period_report_capsule",
]
