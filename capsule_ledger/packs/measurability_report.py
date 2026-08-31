# SPDX-License-Identifier: Apache-2.0
"""``[pack-propose-generic]``: a GENERIC "would this pack work" report --
for ANY pack (``standard-vendor``, a prospect's edited copy, airline-engagement,
whatever ``load_pack_dir`` can parse), read each outcome's already-existing
``tier``/``mode``/``evidence_instrument`` fields and report, per outcome,
whether an oracle can check it (``resolves``) or whether nothing in the
corpus carries the signal it would need (``missing_instrument`` -- itself
the honest, reportable finding, never silently dropped).

**Reuse, not reinvention.** The actual resolve-check (does a structured
field or tool-call name show up anywhere in a unit's messages) is
``corpus_verify.resolves_instrument`` -- this module wraps it, it does not
reimplement it. There is exactly one resolve-check implementation in this
package.

**Fold-mode rows and the unified fold seam.** ``fold_rollup``/
``fold_counterparty``/``fold_agent``/``fold_cohort`` rows never get their
result computed here (that would mean reimplementing fold/rollup
semantics, which this module does not do) -- instead each fold-mode row is
projected onto a ``folds.FoldDefinition`` and its ``core_definition_digest()``
is read through the de-fork seam (``folds/account_core.py`` ->
``capsule_emit.account``, the same seam ``[account-fold-core-unify]``/#107
landed), so the report cites a real, cross-repo-checkable digest rather
than a report-local one. There remain intentionally TWO digests in this
codebase: the ledger's own authoring ``FoldDefinition.definition_digest()``
(unrelated, not surfaced here) and the neutral ``core_definition_digest()``
(the one this report prints, labeled explicitly so the two are never
confused).

**Stage 1b [LOCKED]: ``fold_counterparty``/``fold_cohort`` need the SAME
entity across multiple corpus units to be showable at all** (a trend needs
more than one point). A corpus with no repeat entity traffic (e.g. a
one-off-conversation demo corpus) genuinely cannot show these rows --
that is reported explicitly (``"can't be shown -- not enough repeat
traffic in this demo"``), never silently excluded from the report.
``entity_key`` has no default: the generic corpus shape this module
accepts (``{"messages": [...]}}``) carries no built-in notion of
"counterparty," so guessing one (e.g. defaulting to a specific field name)
would silently mis-scope the check on a corpus shaped differently --
callers must say explicitly how to identify a repeat entity in their own
corpus.

**Scope, held hard:** this is a measurability report -- what CAN be
checked, not a coverage package, not enrollment, not disclosure. It does
not touch ``guards``/``enforce`` (the forward/enforcement path) at all.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from ..folds import DERIVATION_DETERMINISTIC, DERIVATION_MODEL_ASSISTED, FoldDefinition, ReadField, Reduce
from .corpus_verify import resolves_instrument
from .schema import Outcome, PackDefinition

__all__ = [
    "STATUS_RESOLVES",
    "STATUS_MISSING_INSTRUMENT",
    "STATUS_NOT_ENOUGH_REPEAT_TRAFFIC",
    "STATUS_REFUSED",
    "NOT_ENOUGH_REPEAT_TRAFFIC_DETAIL",
    "MeasurabilityRow",
    "build_measurability_report",
    "render_terminal",
]

STATUS_RESOLVES = "resolves"
STATUS_MISSING_INSTRUMENT = "missing_instrument"
STATUS_NOT_ENOUGH_REPEAT_TRAFFIC = "not_enough_repeat_traffic"
# A statement that is too open-ended to ever be checked, REGARDLESS of what
# data is available -- distinct from missing_instrument (measurable in
# principle, just not on THIS corpus). Refused mechanically at compile time
# from the statement's own shape (compiler.vocabulary.REFUSAL_REASON_CODES /
# compiler.effect_model.compile_effect_claim), never by scanning a corpus.
STATUS_REFUSED = "refused"

# Stage 1b's own locked wording -- printed verbatim, not paraphrased, so a
# test can pin the exact string and a report reader always sees the same
# honest line regardless of which outcome/pack triggered it.
NOT_ENOUGH_REPEAT_TRAFFIC_DETAIL = "can't be shown -- not enough repeat traffic in this demo"

# Only these two modes need the SAME-ENTITY-ACROSS-MULTIPLE-UNITS story
# (Stage 1b, locked). fold_rollup rolls up WITHIN one unit/session (every
# unit qualifies); fold_agent's own repeat-trajectory story is structurally
# similar but was not named in the lock -- out of scope here, flagged in
# the PR rather than silently expanded to.
_REPEAT_TRAFFIC_GATED_MODES = frozenset({"fold_counterparty", "fold_cohort"})

# All four fold modes route their digest through the unified seam, per the
# task brief -- distinct from which ones are repeat-traffic gated.
_FOLD_MODES = frozenset({"fold_rollup", "fold_counterparty", "fold_agent", "fold_cohort"})


@dataclass(frozen=True)
class MeasurabilityRow:
    outcome_id: str
    tier: str
    mode: str
    status: str  # STATUS_RESOLVES | STATUS_MISSING_INSTRUMENT | STATUS_NOT_ENOUGH_REPEAT_TRAFFIC
    detail: str
    # Fold-mode rows only -- the neutral capsule_emit.account digest for this
    # row's projected FoldDefinition, read through folds/account_core.py.
    # None for structural/judged/value rows (they carry no fold at all).
    core_definition_digest: str | None = None


def _instrument_field_path(outcome: Outcome) -> str:
    instrument = outcome.evidence_instrument
    assert instrument is not None
    return instrument.field or instrument.name or outcome.id


def _fold_definition_for(outcome: Outcome) -> FoldDefinition:
    """Project ``outcome`` onto a ``FoldDefinition`` purely to obtain a real,
    cross-repo-checkable ``core_definition_digest()`` through the de-fork
    seam -- this NEVER evaluates, rolls up, or asserts a result; the digest
    is the only thing this report consumes from it. ``judged`` outcomes map
    onto ``model_assisted`` (mirrors ``compiler.compile._model_assisted_fold``'s
    own class-marker mapping); every other fold mode is ``deterministic``."""
    reads = (ReadField(path=_instrument_field_path(outcome) if outcome.evidence_instrument else outcome.id, erasure_class="commitment-ok"),)
    derivation_class = DERIVATION_MODEL_ASSISTED if outcome.mode == "judged" else DERIVATION_DETERMINISTIC
    return FoldDefinition(
        fold_id=f"measurability_report.{outcome.id.lower()}/1.0.0",
        reads=reads,
        reduce=Reduce(reducer="count"),
        emit=f"{outcome.id}.{outcome.mode}.measurability",
        derivation_class=derivation_class,
    )


def _has_repeat_entity(units: list[Mapping[str, Any]], entity_key: Callable[[Mapping[str, Any]], str]) -> bool:
    seen: set[str] = set()
    for unit in units:
        key = entity_key(unit)
        if key in seen:
            return True
        seen.add(key)
    return False


def _instrument_status(outcome: Outcome, units: list[Mapping[str, Any]]) -> tuple[str, str]:
    """The plain resolve-check shared by structural/judged/value rows AND
    the two fold modes that aren't repeat-traffic gated (fold_rollup,
    fold_agent) -- identical logic regardless of mode, since the underlying
    question ("does the declared instrument show up anywhere in this
    corpus") doesn't depend on mode at all."""
    instrument = outcome.evidence_instrument
    if instrument is None:
        # Nothing declared as missing -- e.g. a real, already-measured row
        # (J1-J6/F1-style: measurability == "measured"). Not a
        # declared-not-measured claim, so there is no instrumentation gap
        # for this oracle to report on.
        return STATUS_RESOLVES, "no evidence_instrument declared -- not a declared-not-measured row"
    resolved = any(resolves_instrument(instrument, unit.get("messages") or ()) for unit in units)
    if resolved:
        return STATUS_RESOLVES, f"evidence_instrument {instrument.to_dict()} resolves on this corpus"
    return (
        STATUS_MISSING_INSTRUMENT,
        f"MISSING INSTRUMENT: evidence_instrument {instrument.to_dict()} does not resolve on this corpus",
    )


def build_measurability_report(
    pack: PackDefinition,
    corpus: Iterable[Mapping[str, Any]],
    *,
    entity_key: Callable[[Mapping[str, Any]], str],
) -> tuple[MeasurabilityRow, ...]:
    """Run every outcome in ``pack`` against ``corpus`` and report
    resolves/missing_instrument/not_enough_repeat_traffic/refused per row.
    No grading, no pass/fail counts -- a feasibility report, not
    ``propose``'s grading engine (which only exists for one hand-authored
    pack today; this is deliberately lighter-weight and works for any
    pack).

    A ``REFUSED`` outcome (``forward_verdict``/``backward_verdict`` ==
    ``"REFUSED"`` -- ``compiler.vocabulary.REFUSAL_REASON_CODES``: an
    unbounded goal, a causation overclaim, a felt-state claim) is checked
    FIRST and short-circuits everything else for that row: it is too
    open-ended to be checkable regardless of what data is available, so
    neither the instrument check nor a fold digest applies -- reporting
    either would imply "measurable, just not here yet", which is false for
    a refused statement.

    ``entity_key`` is REQUIRED, no default: the generic corpus shape here
    has no built-in "counterparty" concept, so guessing a default field
    name would silently mis-scope the Stage-1b repeat-traffic check on a
    corpus shaped differently than whatever the guess assumed.
    """
    units = list(corpus)  # materialized once; every outcome scans it independently, same convention as corpus_verify
    rows: list[MeasurabilityRow] = []
    for outcome in pack.outcomes:
        if outcome.forward_verdict == "REFUSED" or outcome.backward_verdict == "REFUSED":
            reason = outcome.refusal_reason_code or "no refusal_reason_code declared"
            rows.append(
                MeasurabilityRow(
                    outcome.id, outcome.tier, outcome.mode, STATUS_REFUSED,
                    f"REFUSED (compile-time, no corpus dependency): {reason}",
                )
            )
            continue
        core_digest = _fold_definition_for(outcome).core_definition_digest() if outcome.mode in _FOLD_MODES else None
        if outcome.mode in _REPEAT_TRAFFIC_GATED_MODES and not _has_repeat_entity(units, entity_key):
            rows.append(
                MeasurabilityRow(
                    outcome.id, outcome.tier, outcome.mode,
                    STATUS_NOT_ENOUGH_REPEAT_TRAFFIC, NOT_ENOUGH_REPEAT_TRAFFIC_DETAIL,
                    core_definition_digest=core_digest,
                )
            )
            continue
        status, detail = _instrument_status(outcome, units)
        rows.append(MeasurabilityRow(outcome.id, outcome.tier, outcome.mode, status, detail, core_definition_digest=core_digest))
    return tuple(rows)


def render_terminal(rows: tuple[MeasurabilityRow, ...]) -> str:
    glyphs = {
        STATUS_RESOLVES: "✓",
        STATUS_MISSING_INSTRUMENT: "⚠",
        STATUS_NOT_ENOUGH_REPEAT_TRAFFIC: "⚠",
        STATUS_REFUSED: "✗",  # same glyph convention as airline_engagement_pack.py/tau2_pack_outcomes_walkthrough.py
    }
    lines = [f"measurability report -- {len(rows)} outcome(s)", ""]
    for row in rows:
        glyph = glyphs.get(row.status, "?")
        lines.append(f"  {glyph} {row.outcome_id}  tier={row.tier}  mode={row.mode}  status={row.status}")
        lines.append(f"      {row.detail}")
        if row.core_definition_digest is not None:
            lines.append(f"      core_definition_digest: {row.core_definition_digest}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
