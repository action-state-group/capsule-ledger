# SPDX-License-Identifier: Apache-2.0
"""The fold-based terms report renderer (terms-to-report design §3): "the
report is F evaluated over a committed range as-of a checkpoint. No model
runs at report time." This module turns a compiled terms document
(``terms_desk.compile_terms_document``) plus a records slice (subject
capsules, satellite verdict capsules, and epoch-open records -- the same
"records: list[dict]" convention ``terms_desk.evaluate_term_fold`` already
uses) into rendered report lines, reusing the real fold engine
(``folds.engine.evaluate_all``) for every count -- no hand-rolled
aggregation, "no new fold engine" (design §9), same discipline
``terms_desk.py`` already follows.

**Rules this renderer enforces structurally, not by convention** (design
§3, carried whole from the outcome-compiler report design it extends):

- **Refusal rows render.** A REFUSED term appears with its ``clause_ref``
  and reason code -- "the refused row is what makes the passed rows
  credible" -- never silently dropped.
- **Paired metrics or nothing.** Every rate this module could report is
  exposed only as an ``(n, m)`` pair (``TermReportLine.coverage_n``/
  ``coverage_m``) -- there is no bare-percentage field to accidentally
  ship.
- **Every number carries a fold envelope.** ``FoldEnvelope`` names the
  ``f_digest`` this line's numbers are governed by (the term's own
  compiled ``F_i``, pinned at T1 -- never the renderer's own ad-hoc
  counting definition, which is a replay detail, not a compiled
  commitment), the record range, the checkpoint root, ``as_of``, and the
  epoch -- "(range, as_of, epoch) are formal parameters of every compiled
  F_i from T1" (design §3 [rev]).
- **Mid-period renegotiation partitions by ``c_digest``, never blends.**
  Every judged term's verdict rows are grouped first by
  ``term.c_digest`` (``terms_desk.compiled_term_digest``'s own value) --
  two compiled versions of "the same" term_id render as two separate
  lines, each over its own sub-range, exactly design §3 [rev]'s rule.
- **Per-epoch lines, never blended.** Within one ``c_digest`` partition,
  verdict rows are grouped again by ``epoch`` -- design §4: "two coverage
  lines, never one blended number."
- **Clause_ref is the provenance column** (design §1 [rev4] / §3 [rev4]):
  carried on every line and every refusal row, walkable back to the
  confirmed term.
- **Caveats render, never silently.** A same-family caveat (design §4,
  computed here from ``epoch_registry.same_family_epoch_pairs``) and a
  self-seeded-sampler caveat (design §5, computed by chunk 4's
  ``judge_agent.sampler.AdjudicationSeed.to_caveat`` and passed in here via
  ``epoch_caveats`` -- this module never re-derives sampler state, it only
  has somewhere to render what the sampler already decided) both attach to
  every line for the epoch(s) they concern.

**Why this reads satellite verdict capsules by a plain event-name string
instead of importing ``capsule_compiler.judge_agent.satellite``.**
capsule-compiler depends on capsule-ledger (``judge_agent.satellite``
imports ``capsule_ledger.ledger.api``), never the reverse -- importing it
back from here would invert that dependency. ``EVENT_SATELLITE_VERDICT``
below is intentionally a duplicated literal, not an import; its value must
stay in lockstep with ``capsule_compiler.judge_agent.satellite.
EVENT_SATELLITE_VERDICT`` by convention, the same way this module already
treats the verdict payload's JSON shape (design §2 [rev]'s fenced schema)
as a wire contract rather than a shared Python type. ``EVENT_RUN_SUMMARY``
below is the same convention, kept in lockstep with
``capsule_compiler.judge_agent.satellite.EVENT_RUN_SUMMARY``.

**Coverage denominator is sourced from the run-summary capsule, not
reinvented from verdict rows (adversarial pass Attack 4, launch-blocker).**
A unit that never got any verdict row sealed for a term -- silently
dropped mid-run, not ABSTAIN, not judge-asserted inapplicable -- is
invisible to a denominator built purely from ``records``' verdict rows:
coverage reads n/n = 100% even though the true population (design §2
[rev]'s "units in range", committed in the closing run-summary capsule,
independent of which verdicts happened to seal) was larger. For every
judged-term line, this module cross-checks the verdict-row-derived count
against the matching run-summary capsule's ``units_in_range`` when one is
present for that epoch, sources ``units_in_range`` from the honest
run-summary count, and renders a ``coverage_discrepancy`` caveat -- never
a silent pick-one -- when the two disagree; ``verdict_rows_n`` always
carries the row-derived count too, so neither number is hidden.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..folds.definition import FilterClause, FoldDefinition, ReadField, Reduce
from ..folds.engine import evaluate_all
from .epoch_registry import EpochOpen, same_family_epoch_pairs
from .terms_desk import CompiledTerm, compiled_term_digest, evaluate_term_fold

__all__ = [
    "EVENT_SATELLITE_VERDICT",
    "EVENT_RUN_SUMMARY",
    "ABSTAIN",
    "FoldEnvelope",
    "TermReportLine",
    "RefusalRow",
    "TermsReport",
    "render_terms_report",
]

# capsule_compiler.judge_agent.satellite.EVENT_SATELLITE_VERDICT, duplicated
# intentionally -- see module docstring for why this is not an import.
EVENT_SATELLITE_VERDICT = "judge_agent_verdict"
# capsule_compiler.judge_agent.satellite.EVENT_RUN_SUMMARY, same convention.
EVENT_RUN_SUMMARY = "judge_agent_run_summary"
ABSTAIN = "ABSTAIN"

_VERDICT_READ_PATHS = (
    "asg_payload.event",
    "asg_payload.detail.term.term_id",
    "asg_payload.detail.term.c_digest",
    "asg_payload.detail.epoch",
    "asg_payload.detail.applicable",
    "asg_payload.detail.verdict",
)
_VERDICT_READS = tuple(ReadField(path=p, erasure_class="commitment-ok") for p in _VERDICT_READ_PATHS)


def _slug(term_id: str) -> str:
    return term_id.split("/")[0].replace(".", "_").replace("-", "_")


@dataclass(frozen=True)
class FoldEnvelope:
    """design §3's fenced envelope: ``{f_digest, record range, checkpoint
    root, as_of}``, plus ``epoch`` (design §3 [rev]: a formal parameter of
    every compiled ``F_i`` from T1, not bolted on later)."""

    f_digest: str | None
    range_start: int
    range_end: int
    checkpoint_root: str | None
    as_of: str | None
    epoch: str | None

    def to_dict(self) -> dict:
        return {
            "f_digest": self.f_digest,
            "range": [self.range_start, self.range_end],
            "checkpoint_root": self.checkpoint_root,
            "as_of": self.as_of,
            "epoch": self.epoch,
        }


@dataclass(frozen=True)
class TermReportLine:
    """One rendered line: one term, one compiled version (``c_digest``),
    one epoch (or ``None`` for a deterministic-rule term, which has no
    judge epoch to partition by). ``verdict_counts`` carries the full
    breakdown (e.g. ``{"pass": 12, "fail": 3, "ABSTAIN": 1}``) rather than
    hard-coded pass/fail fields -- a term's ``verdict_schema`` is a closed
    enum or bounded scalar, never fixed to boolean (design §1)."""

    term_id: str
    clause_ref: str | None
    c_digest: str
    epoch: str | None
    group_key: str | None
    verdict_counts: Mapping[str, int]
    applicable_n: int
    inapplicable_n: int
    units_in_range: int
    envelope: FoldEnvelope
    caveats: tuple[Mapping[str, Any], ...] = ()
    # Attack 4 (adversarial pass): the row-derived count is always carried
    # alongside `units_in_range` so a reader can see both numbers, never
    # just the one this module chose to trust. `coverage_discrepancy` is
    # True only when a run-summary capsule for this epoch was found AND
    # its `units_in_range` disagrees with `verdict_rows_n`.
    verdict_rows_n: int | None = None
    coverage_discrepancy: bool = False

    @property
    def coverage_n(self) -> int:
        """judged_units -- applicable rows that got a real verdict, never
        an ABSTAIN (design §3: "coverage = judged_units / units_in_range")."""
        return self.applicable_n - self.verdict_counts.get(ABSTAIN, 0)

    @property
    def coverage_m(self) -> int:
        return self.units_in_range

    def to_dict(self) -> dict:
        return {
            "term_id": self.term_id,
            "clause_ref": self.clause_ref,
            "c_digest": self.c_digest,
            "epoch": self.epoch,
            "group_key": self.group_key,
            "verdict_counts": dict(self.verdict_counts),
            "applicable_n": self.applicable_n,
            "inapplicable_n": self.inapplicable_n,
            "units_in_range": self.units_in_range,
            "verdict_rows_n": self.verdict_rows_n,
            "coverage_discrepancy": self.coverage_discrepancy,
            "coverage": {"n": self.coverage_n, "m": self.coverage_m},
            "envelope": self.envelope.to_dict(),
            "caveats": [dict(c) for c in self.caveats],
        }


@dataclass(frozen=True)
class RefusalRow:
    """A REFUSED term, rendered -- design §3: "refusal rows render ...
    because the refused row is what makes the passed rows credible."""

    term_id: str
    clause_ref: str | None
    reason_code: str

    def to_dict(self) -> dict:
        return {"term_id": self.term_id, "clause_ref": self.clause_ref, "reason_code": self.reason_code}


@dataclass(frozen=True)
class TermsReport:
    lines: tuple[TermReportLine, ...]
    refusals: tuple[RefusalRow, ...]

    def to_dict(self) -> dict:
        return {"lines": [line.to_dict() for line in self.lines], "refusals": [r.to_dict() for r in self.refusals]}


def _matching_count(
    records: Sequence[dict],
    filters: tuple[FilterClause, ...],
    *,
    range_start: int,
    as_of: str | None,
    fold_id: str,
) -> int:
    """A count over ``records`` via the real fold engine -- reused for both
    the applicability denominator (deterministic-rule terms) and the
    inapplicable-row count (judged terms), never a hand-rolled loop, so
    every number here is subject to the engine's own determinism rules
    (spec §3), same as any other fold."""
    if not filters:
        return len(records)
    reads = tuple(ReadField(path=p, erasure_class="commitment-ok") for p in dict.fromkeys(fc.field for fc in filters))
    definition = FoldDefinition(fold_id=fold_id, reads=reads, filter=filters, key=None, reduce=Reduce(reducer="count"), emit=f"{fold_id}.count")
    traces = evaluate_all(definition, list(records), range_start=range_start, as_of=as_of)
    return next(iter(traces.values())).result if traces else 0


def _verdict_partitions(records: Sequence[dict], term_id: str) -> tuple[tuple[str, str | None], ...]:
    """Every distinct ``(c_digest, epoch)`` pair present among this term's
    sealed verdict rows -- structural discovery of which lines to render,
    not itself a number, so plain iteration (not the fold engine) is the
    right tool; every COUNT built from these partitions goes through
    ``evaluate_all`` below."""
    seen: dict[tuple[str, str | None], None] = {}
    for record in records:
        payload = record.get("asg_payload") or {}
        if payload.get("event") != EVENT_SATELLITE_VERDICT:
            continue
        detail = payload.get("detail") or {}
        term = detail.get("term") or {}
        if term.get("term_id") != term_id:
            continue
        seen.setdefault((term.get("c_digest"), detail.get("epoch")), None)
    return tuple(seen.keys())


def _verdict_breakdown(
    records: Sequence[dict], term_id: str, c_digest: str, epoch: str | None, *, range_start: int, as_of: str | None
) -> dict[str, int]:
    filters = [
        FilterClause(field="asg_payload.event", op="eq", value=EVENT_SATELLITE_VERDICT),
        FilterClause(field="asg_payload.detail.term.term_id", op="eq", value=term_id),
        FilterClause(field="asg_payload.detail.term.c_digest", op="eq", value=c_digest),
        FilterClause(field="asg_payload.detail.applicable", op="eq", value=True),
    ]
    if epoch is not None:
        filters.append(FilterClause(field="asg_payload.detail.epoch", op="eq", value=epoch))
    definition = FoldDefinition(
        fold_id=f"compiler.terms_report.{_slug(term_id)}.verdict_count/1.0.0",
        reads=_VERDICT_READS,
        filter=tuple(filters),
        key="asg_payload.detail.verdict",
        reduce=Reduce(reducer="count"),
        emit=f"{term_id}.verdict_count",
    )
    traces = evaluate_all(definition, list(records), range_start=range_start, as_of=as_of)
    return {str(k): t.result for k, t in traces.items()}


def _inapplicable_count(
    records: Sequence[dict], term_id: str, c_digest: str, epoch: str | None, *, range_start: int, as_of: str | None
) -> int:
    filters = (
        FilterClause(field="asg_payload.event", op="eq", value=EVENT_SATELLITE_VERDICT),
        FilterClause(field="asg_payload.detail.term.term_id", op="eq", value=term_id),
        FilterClause(field="asg_payload.detail.term.c_digest", op="eq", value=c_digest),
        FilterClause(field="asg_payload.detail.applicable", op="eq", value=False),
    ) + ((FilterClause(field="asg_payload.detail.epoch", op="eq", value=epoch),) if epoch is not None else ())
    return _matching_count(
        records,
        filters,
        range_start=range_start,
        as_of=as_of,
        fold_id=f"compiler.terms_report.{_slug(term_id)}.inapplicable_count/1.0.0",
    )


def _run_summary_units_in_range(records: Sequence[dict], epoch: str) -> int | None:
    """The honest population for ``epoch``, as committed by the closing
    run-summary capsule (design §2 [rev]: "the run closes with a
    run-summary capsule committing {..., units in range, ...}"), or
    ``None`` if no such capsule is present in this ``records`` slice --
    that absence is not itself an error (a report can predate chunk 6's
    daily orchestrator wiring), it just means there is no independent
    population to cross-check the verdict rows against. When more than one
    run-summary capsule exists for the same epoch (a rerun), the last one
    in append order wins -- the same "latest wins" convention
    ``capsule_compiler.judge_agent.satellite.latest_run_summary`` uses."""
    found: int | None = None
    for record in records:
        payload = record.get("asg_payload") or {}
        if payload.get("event") != EVENT_RUN_SUMMARY:
            continue
        detail = payload.get("detail") or {}
        if detail.get("epoch") != epoch:
            continue
        units_in_range = detail.get("units_in_range")
        if isinstance(units_in_range, int):
            found = units_in_range
    return found


def _same_family_caveat(epoch: str, siblings: Sequence[str], same_family_pairs: frozenset, judge_family_by_epoch: Mapping[str, str]) -> dict | None:
    for other in siblings:
        if other == epoch or other is None:
            continue
        if frozenset((epoch, other)) in same_family_pairs:
            return {
                "caveat": "same_family_judging",
                "detail": (
                    f"epoch {epoch!r} and epoch {other!r} share judge family "
                    f"{judge_family_by_epoch.get(epoch)!r}; inter-epoch disagreement between them is "
                    "correlated opinion, not an independent check (design §4)."
                ),
            }
    return None


def render_terms_report(
    compiled_terms: Sequence[CompiledTerm],
    records: Sequence[dict],
    *,
    range_start: int = 0,
    as_of: str | None = None,
    checkpoint_root: str | None = None,
    epoch_opens: Sequence[EpochOpen] = (),
    epoch_caveats: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> TermsReport:
    """The report: ``F`` evaluated over ``records`` (design §3). ``records``
    is a plain slice -- subject capsules for deterministic-rule terms,
    satellite verdict capsules for judged terms, both already scoped to the
    range being reported (the same convention ``evaluate_term_fold`` uses;
    this module invents no new range mechanism). ``epoch_opens`` supplies
    the registry entries needed for the same-family caveat (design §4);
    ``epoch_caveats`` is a caller-supplied ``epoch_id -> caveat dicts`` map
    for caveats this module does not itself compute (design §5's
    self-seeded-sampler caveat, produced by chunk 4's
    ``AdjudicationSeed.to_caveat``) -- rendered verbatim, merged with the
    same-family caveat this module does compute."""
    epoch_caveats = epoch_caveats or {}
    judge_family_by_epoch = {e.epoch_id: e.judge_family for e in epoch_opens}
    same_family_pairs = same_family_epoch_pairs(epoch_opens)
    range_end = range_start + len(records) - 1 if records else range_start - 1

    lines: list[TermReportLine] = []
    refusals: list[RefusalRow] = []

    for ct in compiled_terms:
        if ct.refusal_reason_code is not None:
            refusals.append(RefusalRow(term_id=ct.term_id, clause_ref=ct.clause_ref, reason_code=ct.refusal_reason_code))
            continue

        if ct.judge_or_rule is not None and ct.judge_or_rule.kind == "judge":
            partitions = _verdict_partitions(records, ct.term_id)
            epochs_by_c_digest: dict[str, list[str | None]] = {}
            for c_digest, epoch in partitions:
                epochs_by_c_digest.setdefault(c_digest, []).append(epoch)

            for c_digest, epoch in partitions:
                verdict_counts = _verdict_breakdown(records, ct.term_id, c_digest, epoch, range_start=range_start, as_of=as_of)
                inapplicable_n = _inapplicable_count(records, ct.term_id, c_digest, epoch, range_start=range_start, as_of=as_of)
                applicable_n = sum(verdict_counts.values())
                verdict_rows_n = applicable_n + inapplicable_n

                run_summary_n = _run_summary_units_in_range(records, epoch) if epoch is not None else None
                coverage_discrepancy = run_summary_n is not None and run_summary_n != verdict_rows_n
                units_in_range = run_summary_n if run_summary_n is not None else verdict_rows_n

                caveats: list[Mapping[str, Any]] = list(epoch_caveats.get(epoch, ())) if epoch is not None else []
                if epoch is not None:
                    caveat = _same_family_caveat(epoch, epochs_by_c_digest.get(c_digest, ()), same_family_pairs, judge_family_by_epoch)
                    if caveat is not None:
                        caveats.append(caveat)
                if coverage_discrepancy:
                    caveats.append(
                        {
                            "caveat": "coverage_discrepancy",
                            "detail": (
                                f"run-summary capsule for epoch {epoch!r} commits units_in_range="
                                f"{run_summary_n}, but only {verdict_rows_n} verdict row(s) are sealed for "
                                f"term {ct.term_id!r} at c_digest {c_digest!r} -- some units may have been "
                                "silently dropped rather than judged, abstained, or marked inapplicable."
                            ),
                        }
                    )

                lines.append(
                    TermReportLine(
                        term_id=ct.term_id,
                        clause_ref=ct.clause_ref,
                        c_digest=c_digest,
                        epoch=epoch,
                        group_key=None,
                        verdict_counts=verdict_counts,
                        applicable_n=applicable_n,
                        inapplicable_n=inapplicable_n,
                        units_in_range=units_in_range,
                        envelope=FoldEnvelope(
                            f_digest=ct.f_digest,
                            range_start=range_start,
                            range_end=range_end,
                            checkpoint_root=checkpoint_root,
                            as_of=as_of,
                            epoch=epoch,
                        ),
                        caveats=tuple(caveats),
                        verdict_rows_n=verdict_rows_n,
                        coverage_discrepancy=coverage_discrepancy,
                    )
                )
            continue

        # DETERMINISTIC / DETERMINISTIC-RULE / MANUAL / WITH-INSTRUMENTATION:
        # an attainment-style fold over subject records, never over
        # satellite verdict capsules -- there are none for a rule term.
        c_digest = compiled_term_digest(ct)
        applicable_n = _matching_count(
            records,
            ct.applicability.filters,
            range_start=range_start,
            as_of=as_of,
            fold_id=f"compiler.terms_report.{_slug(ct.term_id)}.applicable_count/1.0.0",
        )
        envelope = FoldEnvelope(
            f_digest=ct.f_digest, range_start=range_start, range_end=range_end, checkpoint_root=checkpoint_root, as_of=as_of, epoch=None
        )
        traces = evaluate_term_fold(ct, list(records), range_start=range_start, as_of=as_of, epoch=None)
        if not traces:
            lines.append(
                TermReportLine(
                    term_id=ct.term_id,
                    clause_ref=ct.clause_ref,
                    c_digest=c_digest,
                    epoch=None,
                    group_key=None,
                    verdict_counts={},
                    applicable_n=applicable_n,
                    inapplicable_n=0,
                    units_in_range=applicable_n,
                    envelope=envelope,
                    caveats=(),
                )
            )
            continue
        for group_key, trace in traces.items():
            n = trace.result if isinstance(trace.result, int) else 0
            lines.append(
                TermReportLine(
                    term_id=ct.term_id,
                    clause_ref=ct.clause_ref,
                    c_digest=c_digest,
                    epoch=None,
                    group_key=str(group_key),
                    verdict_counts={"attained": n},
                    applicable_n=applicable_n,
                    inapplicable_n=0,
                    units_in_range=applicable_n,
                    envelope=envelope,
                    caveats=(),
                )
            )

    return TermsReport(lines=tuple(lines), refusals=tuple(refusals))
