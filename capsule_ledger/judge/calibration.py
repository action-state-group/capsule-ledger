# SPDX-License-Identifier: Apache-2.0
"""The calibration harness seam (design §6c item 4): computes plain, measured
judge-quality stats -- agreement rate, drift rate -- from a ledger's own
``judge_judgment`` / ``judge_adjudication`` / ``judge_drift_check`` history,
keyed by ``judge_pin_digest`` (``capsules.judge_pin_digest`` -- the
reproducible model+prompt identity, not a point-in-time value).

**Hooks to record-grounding-bench.** The flagship grounding benchmark
(tau2-bench, driven by the outcomes-schema pack/fold machinery -- see
``[ldg-cs-p6-demo-and-experiment]``) does not exist in this repo yet; this
module is the consumer-side seam it will feed once it lands, not a live
integration today. Until then, ``compute_judge_calibration_stats`` operates
over whatever judgments/adjudications/drift-checks a ledger already has --
real records, just not yet a labeled benchmark population.

**No calibration weighting scheme lives here** -- only plain descriptive
stats (counts and rates). Any bias-correction, calibration-weight
propagation, or similar method built on top of these numbers is out of
scope for this module and this repo (G-IP1/C3).
"""
from __future__ import annotations

from dataclasses import dataclass

from ..ledger.api import LedgerAPI, ScanQuery
from .capsules import EVENT_JUDGMENT, find_adjudications_for_judgment, find_drift_checks_for_judgment

__all__ = ["JudgeCalibrationStats", "compute_judge_calibration_stats"]


@dataclass(frozen=True)
class JudgeCalibrationStats:
    """Plain measured stats for one ``judge_pin_digest``, as of the moment
    ``compute_judge_calibration_stats`` was called -- every field is
    re-derivable by re-scanning the ledger, never a stored/asserted value.
    """

    judge_pin_digest: str
    judgment_count: int
    adjudicated_count: int
    agreement_count: int
    agreement_rate: float | None
    drift_check_count: int
    drift_count: int
    drift_rate: float | None


def compute_judge_calibration_stats(ledger: LedgerAPI, judge_pin_digest: str) -> JudgeCalibrationStats:
    """Scan ``ledger`` for every ``judge_judgment`` sealed under
    ``judge_pin_digest``, then fold in their adjudications and drift checks.
    ``agreement_rate``/``drift_rate`` are ``None`` (not ``0.0``) when there is
    no adjudicated/checked population to measure yet -- an unmeasured judge
    is a different, honest state from a judge measured at 0% agreement,
    matching this codebase's own never-impute-into-a-numerator discipline
    elsewhere (``ldg-outcome-declaration-schema``'s "never impute an
    unjudged/unconfirmed session into either numerator")."""
    judgment_ids: list[str] = []
    for record in ledger.scan(ScanQuery(action_type="fyi")):
        payload = record.capsule.get("asg_payload") or {}
        if payload.get("event") != EVENT_JUDGMENT:
            continue
        pin = (payload.get("detail") or {}).get("judge_pin") or {}
        if pin.get("judge_pin_digest") == judge_pin_digest:
            judgment_ids.append(record.capsule_id)

    adjudicated_count = 0
    agreement_count = 0
    for judgment_id in judgment_ids:
        adjudications = find_adjudications_for_judgment(ledger, judgment_id)
        if not adjudications:
            continue
        adjudicated_count += 1
        # Append-ordered scan -- the last adjudication is the current disposition.
        latest = adjudications[-1]
        detail = (latest.capsule.get("asg_payload") or {}).get("detail") or {}
        if detail.get("agrees_with_judge") is True:
            agreement_count += 1

    drift_check_count = 0
    drift_count = 0
    for judgment_id in judgment_ids:
        for check in find_drift_checks_for_judgment(ledger, judgment_id):
            drift_check_count += 1
            detail = (check.capsule.get("asg_payload") or {}).get("detail") or {}
            if detail.get("drifted") is True:
                drift_count += 1

    return JudgeCalibrationStats(
        judge_pin_digest=judge_pin_digest,
        judgment_count=len(judgment_ids),
        adjudicated_count=adjudicated_count,
        agreement_count=agreement_count,
        agreement_rate=(agreement_count / adjudicated_count) if adjudicated_count else None,
        drift_check_count=drift_check_count,
        drift_count=drift_count,
        drift_rate=(drift_count / drift_check_count) if drift_check_count else None,
    )
