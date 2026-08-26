# SPDX-License-Identifier: Apache-2.0
"""Scan a ledger over a period and assemble the three blocks design §3.6
specifies. Reads T1/T2/T4 records to the P1 schema (manager parallel-spawn
note, [ldg-cs-p4-capsule-report]: build to the P1 schema, treat P3's
``confirm``-produced capsules as schema-conformant inputs -- P3 is in
flight and this task does not block on it).

**The v1 evidence join, stated so it cannot be mistaken for more than it
is.** Matching a declared ``Outcome`` to the offer/response capsules that
evidence it is, in general, the evidence-rule lint (``packs/schema.py``'s
``Outcome.evidence_rule`` docstring: "a later, separate task", Track A/B1).
This module does not implement that lint. It implements exactly one
mechanical join: an ``offer`` capsule's ``offer_id`` belongs to outcome
``O`` when ``offer_id == O.id`` or ``offer_id`` starts with ``f"{O.id}/"``.
That is the full join. An outcome whose evidence is not offer/response
shaped (e.g. a fulfillment capsule this codebase has not built a builder
for yet) honestly renders 0 of 0 rather than a fabricated number.

A refused outcome is matched to its sealed ``compiler.refusal`` capsule by
``statement_digest`` -- SHA-256 over the outcome's own ``statement`` text,
the same convention ``tests/test_compiler_records.py`` already uses.
"""
from __future__ import annotations

import hashlib
from datetime import datetime

from ..compiler.acceptance import EVENT_DECLARATION_ACCEPTANCE, EVENT_REFUSAL_ACKNOWLEDGMENT
from ..compiler.compilation_record import EVENT_COMPILATION_RECORD
from ..compiler.offer_response import EVENT_OFFER, EVENT_RESPONSE
from ..compiler.refusal import EVENT_REFUSAL
from ..compiler.scope_census import EVENT_SCOPE_CENSUS
from ..compiler.vocabulary import display_string
from ..ledger.api import LedgerAPI, ScanQuery
from ..ledger.records import LedgerRecord
from ..packs.schema import PackDefinition
from .model import (
    AUDIENCES,
    DeferralRow,
    NotClaimableRow,
    OutcomeCoverageRow,
    PeriodReport,
    VerifyRow,
    WhatHappenedBlock,
    WhatWasPromisedBlock,
)

__all__ = ["statement_digest", "build_period_report"]


def statement_digest(statement: str) -> str:
    return hashlib.sha256(statement.encode("utf-8")).hexdigest()


def _event(capsule: dict) -> str | None:
    return (capsule.get("asg_payload") or {}).get("event")


def _detail(capsule: dict) -> dict:
    return (capsule.get("asg_payload") or {}).get("detail") or {}


def _offer_belongs_to(offer_id: str, outcome_id: str) -> bool:
    return offer_id == outcome_id or offer_id.startswith(outcome_id + "/")


def _age_label(offered_at: str, as_of: str) -> str:
    try:
        t0 = datetime.fromisoformat(offered_at.replace("Z", "+00:00"))
        t1 = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return "age unknown"
    seconds = (t1 - t0).total_seconds()
    if seconds < 0:
        return "age unknown"
    days = int(seconds // 86400)
    if days >= 1:
        return f"{days}d"
    hours = int(seconds // 3600)
    if hours >= 1:
        return f"{hours}h"
    minutes = int(seconds // 60)
    return f"{minutes}m"


class _VerifyRegister:
    """De-duplicating accumulator for block-3 rows -- a capsule cited twice
    (e.g. an offer already cited by one outcome, referenced again in the
    deferral register) gets exactly one verify row."""

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self.rows: list[VerifyRow] = []

    def add(self, label: str, capsule_id: str | None) -> None:
        if not capsule_id or capsule_id in self._seen:
            return
        self._seen.add(capsule_id)
        self.rows.append(VerifyRow(label=label, capsule_id=capsule_id))

    @property
    def cited_ids(self) -> tuple[str, ...]:
        return tuple(r.capsule_id for r in self.rows)


def build_period_report(
    ledger: LedgerAPI,
    pack: PackDefinition,
    *,
    audience: str,
    since: str | None,
    until: str | None,
    generated_at: str,
) -> PeriodReport:
    if audience not in AUDIENCES:
        raise ValueError(f"audience must be one of {sorted(AUDIENCES)}; got {audience!r}")

    records: list[LedgerRecord] = list(ledger.scan(ScanQuery(since=since, until=until)))

    censuses = [r for r in records if _event(r.capsule) == EVENT_SCOPE_CENSUS]
    acceptances = [r for r in records if _event(r.capsule) == EVENT_DECLARATION_ACCEPTANCE]
    compilations = [r for r in records if _event(r.capsule) == EVENT_COMPILATION_RECORD]
    offers = [r for r in records if _event(r.capsule) == EVENT_OFFER]
    responses = [r for r in records if _event(r.capsule) == EVENT_RESPONSE]
    refusals = [r for r in records if _event(r.capsule) == EVENT_REFUSAL]
    acknowledgments = [r for r in records if _event(r.capsule) == EVENT_REFUSAL_ACKNOWLEDGMENT]

    # scan() is append order (judge/capsules.py's find_latest_* convention);
    # the last match is the most recent -- a re-census/re-acceptance
    # supersedes rather than edits, so "latest" is the live one.
    latest_census = censuses[-1] if censuses else None
    latest_acceptance = acceptances[-1] if acceptances else None
    latest_compilation = compilations[-1] if compilations else None

    census_detail = _detail(latest_census.capsule) if latest_census else {}
    acceptance_detail = _detail(latest_acceptance.capsule) if latest_acceptance else {}
    compilation_detail = _detail(latest_compilation.capsule) if latest_compilation else {}

    verify = _VerifyRegister()
    if latest_census:
        verify.add("scope census (T2)", latest_census.capsule_id)
    if latest_acceptance:
        verify.add("declaration acceptance (T1)", latest_acceptance.capsule_id)
    if latest_compilation:
        verify.add("compilation record (C)", latest_compilation.capsule_id)

    promised = WhatWasPromisedBlock(
        document_digest=census_detail.get("document_digest"),
        census_n=census_detail.get("n"),
        census_m=census_detail.get("m"),
        census_review_by=census_detail.get("review_by"),
        census_capsule_id=latest_census.capsule_id if latest_census else None,
        d_digest=compilation_detail.get("d_digest"),
        c_digest=latest_compilation.capsule_id if latest_compilation else None,
        p_digest=compilation_detail.get("p_digest"),
        f_digest=compilation_detail.get("f_digest"),
        compiler_id=compilation_detail.get("compiler_id"),
        compiler_version=compilation_detail.get("compiler_version"),
        acceptance_capsule_id=latest_acceptance.capsule_id if latest_acceptance else None,
        accepted_by=acceptance_detail.get("accepted_by"),
    )

    responses_by_offer_capsule_id: dict[str, LedgerRecord] = {}
    for r in responses:
        parent = (r.capsule.get("chain") or {}).get("parent_capsule_id")
        if parent:
            responses_by_offer_capsule_id[parent] = r  # last (append order) wins

    refusals_by_statement_digest = {_detail(r.capsule).get("statement_digest"): r for r in refusals}
    acks_by_refusal_capsule_id = {_detail(r.capsule).get("refusal_capsule_id"): r for r in acknowledgments}

    coverage_rows: list[OutcomeCoverageRow] = []
    not_claimable_rows: list[NotClaimableRow] = []
    deferral_rows: list[DeferralRow] = []

    for outcome in pack.outcomes:
        is_refused = "REFUSED" in (outcome.forward_verdict, outcome.backward_verdict)
        is_with_instrumentation = outcome.backward_verdict == "WITH-INSTRUMENTATION"

        if is_refused:
            sd = statement_digest(outcome.statement)
            refusal_record = refusals_by_statement_digest.get(sd)
            ack_record = acks_by_refusal_capsule_id.get(refusal_record.capsule_id) if refusal_record else None
            reason_display = (
                display_string("refusal_reason_code", outcome.refusal_reason_code)
                if outcome.refusal_reason_code
                else display_string("backward_verdict", "REFUSED")
            )
            not_claimable_rows.append(
                NotClaimableRow(
                    outcome_id=outcome.id,
                    statement=outcome.statement,
                    reason_category="refused",
                    reason_display=reason_display,
                    refusal_capsule_id=refusal_record.capsule_id if refusal_record else None,
                    acknowledged=ack_record is not None,
                    acknowledgment_capsule_id=ack_record.capsule_id if ack_record else None,
                )
            )
            if refusal_record:
                verify.add(f"{outcome.id} · refusal", refusal_record.capsule_id)
            if ack_record:
                verify.add(f"{outcome.id} · refusal acknowledgment (T4)", ack_record.capsule_id)
            continue

        if is_with_instrumentation:
            not_claimable_rows.append(
                NotClaimableRow(
                    outcome_id=outcome.id,
                    statement=outcome.statement,
                    reason_category="with_instrumentation",
                    reason_display=display_string("backward_verdict", "WITH-INSTRUMENTATION"),
                    refusal_capsule_id=None,
                    acknowledged=False,
                    acknowledgment_capsule_id=None,
                )
            )
            continue

        matched_offers = [r for r in offers if _offer_belongs_to(_detail(r.capsule).get("offer_id", ""), outcome.id)]
        n = 0
        evidenced: list[str] = []
        for off in matched_offers:
            resp = responses_by_offer_capsule_id.get(off.capsule_id)
            evidenced.append(off.capsule_id)
            verify.add(f"{outcome.id} · offer", off.capsule_id)
            if resp is None:
                continue
            evidenced.append(resp.capsule_id)
            verify.add(f"{outcome.id} · response", resp.capsule_id)
            response_class = _detail(resp.capsule).get("response_class")
            if response_class == "accepted":
                n += 1
            elif response_class == "deferred":
                deferral_rows.append(
                    DeferralRow(
                        offer_id=_detail(off.capsule).get("offer_id", ""),
                        response_capsule_id=resp.capsule_id,
                        offered_at=off.capsule.get("timestamp", ""),
                        age_label=_age_label(off.capsule.get("timestamp", ""), generated_at),
                    )
                )

        coverage_rows.append(
            OutcomeCoverageRow(
                outcome_id=outcome.id,
                statement=outcome.statement,
                forward_verdict=outcome.forward_verdict,
                forward_display=display_string("forward_verdict", outcome.forward_verdict),
                backward_verdict=outcome.backward_verdict,
                backward_display=display_string("backward_verdict", outcome.backward_verdict),
                n=n,
                m=len(matched_offers),
                evidenced_capsule_ids=tuple(evidenced),
            )
        )

    happened = WhatHappenedBlock(
        coverage=tuple(coverage_rows), not_claimable=tuple(not_claimable_rows), deferrals=tuple(deferral_rows)
    )

    return PeriodReport(
        pack_id=pack.pack_id,
        audience=audience,
        since=since,
        until=until,
        generated_at=generated_at,
        promised=promised,
        happened=happened,
        verify_rows=tuple(verify.rows),
        cited_capsule_ids=verify.cited_ids,
    )
