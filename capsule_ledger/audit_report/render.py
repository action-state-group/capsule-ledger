# SPDX-License-Identifier: Apache-2.0
"""Render a :class:`~capsule_ledger.audit_report.model.PeriodReport` as
plain text, in the fixed order design §3.6 specifies: what was promised /
what happened / can I check it. No table-widget dependency -- this is
meant to be readable pasted into an email or a ticket, same reasoning
``cli/format.py``'s helpers already follow.

**Footer line (build plan Phase 4 item 4).** States plainly that
hand-running this command is open source, free forever, and that every
block above and the offline check below are already the full capability
-- nothing in this report is a preview or a subset of something larger.
"Same engine, same records, same offline check" -- never "OSS has fewer
features" (design's honest-sentence rule).
"""
from __future__ import annotations

from .model import PeriodReport

__all__ = ["render_text"]

_TIER_LINE = (
    "capsule report, hand-run on your own files, is open source -- free forever. "
    "This command is the whole verify-it-yourself surface: every block above and "
    "the offline check below are already the full capability, not a preview or a "
    "subset of anything larger. Nothing here is held back."
)


def _fmt_n_of_m(n: int, m: int) -> str:
    return f"{n} of {m}"


def _verify_command(bundle_path: str | None, capsule_id: str) -> str:
    if not bundle_path:
        return f"capsule verify --bundle <report-bundle.json> {capsule_id}"
    return f"capsule verify --bundle {bundle_path} {capsule_id}"


def _render_promised(report: PeriodReport) -> list[str]:
    p = report.promised
    lines = ["## 1. what was promised", ""]
    if p.census_capsule_id:
        lines.append(
            f"scope census: {_fmt_n_of_m(p.census_n, p.census_m)} outcomes/obligations covered "
            f"in document {p.document_digest} -- reviewable again by {p.census_review_by}"
        )
        lines.append(f"  census capsule: {p.census_capsule_id}")
    else:
        lines.append("scope census: not recorded in this period")

    if p.acceptance_capsule_id:
        lines.append(f"declaration accepted by: {p.accepted_by}  (capsule {p.acceptance_capsule_id})")
    else:
        lines.append("declaration acceptance (T1): not recorded in this period")

    if p.c_digest:
        lines.append(
            f"compilation record C: {p.c_digest}  (D={p.d_digest} P={p.p_digest} F={p.f_digest}, "
            f"compiler {p.compiler_id}@{p.compiler_version})"
        )
    else:
        lines.append("compilation record (C): not recorded in this period")
    lines.append("")
    return lines


def _render_happened(report: PeriodReport) -> list[str]:
    h = report.happened
    lines = ["## 2. what happened", "", "### coverage -- Enforced by / Evidenced by", ""]
    if not h.coverage:
        lines.append("(no coverage rows in this period)")
    for row in h.coverage:
        lines.append(f"- {row.outcome_id}: {_fmt_n_of_m(row.n, row.m)}")
        lines.append(f"    statement: {row.statement}")
        lines.append(f"    Enforced by:  {row.forward_display}")
        lines.append(f"    Evidenced by: {row.backward_display}")
    lines.append("")

    lines.append("### not-claimable register")
    lines.append("")
    if not h.not_claimable:
        lines.append("(nothing refused or instrumentation-gated in this period)")
    for row in h.not_claimable:
        ack = f"acknowledged (T4 capsule {row.acknowledgment_capsule_id})" if row.acknowledged else "NOT yet acknowledged"
        lines.append(f"- {row.outcome_id}: {row.reason_display} -- {ack}")
        lines.append(f"    statement: {row.statement}")
    lines.append("")

    lines.append("### deferral aging")
    lines.append("")
    if not h.deferrals:
        lines.append("(no open deferrals in this period)")
    for row in h.deferrals:
        lines.append(f"- {row.offer_id}: deferred, age {row.age_label}  (response {row.response_capsule_id})")
    lines.append("")
    return lines


def _render_verify(report: PeriodReport) -> list[str]:
    lines = ["## 3. can I check it", ""]
    if report.report_capsule_id:
        lines.append(f"this report's own record: {report.report_capsule_id}")
    if report.bundle_path:
        lines.append(f"bundle: {report.bundle_path}")
    lines.append("")
    lines.append("pick any row below and run its command offline -- no network, no permission from us:")
    lines.append("")
    if not report.verify_rows:
        lines.append("(nothing cited in this period)")
    for row in report.verify_rows:
        lines.append(f"- {row.label}: {row.capsule_id}")
        lines.append(f"    {_verify_command(report.bundle_path, row.capsule_id)}")
    lines.append("")
    return lines


def render_text(report: PeriodReport) -> str:
    lines = [
        f"capsule report · {report.pack_id} · period {report.since or '(open)'}..{report.until or '(open)'} "
        f"· audience: {report.audience}",
        f"generated at: {report.generated_at}",
        "",
    ]
    lines.extend(_render_promised(report))
    lines.extend(_render_happened(report))
    lines.extend(_render_verify(report))
    lines.append("---")
    lines.append(_TIER_LINE)
    return "\n".join(lines) + "\n"
