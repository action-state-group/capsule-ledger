# SPDX-License-Identifier: Apache-2.0
"""``ServingConsistencyScorer``: a deterministic ``Scorer`` that judges a
node's *serving* claims over a RANGE of its capsules -- "the machine said it
was running X (model/hardware) before, and Y now; the hardware must not
change."

This is a ``Scorer`` like any other (``scorer.py``'s ``Scorer`` protocol), so
it rides the existing ``JudgeHarness`` end to end: the harness scores it,
pins it, and seals the verdict as a ``judge_judgment`` capsule (chained,
verifiable); ``JudgeHarness.check_drift`` re-runs it over the same range and
seals a ``judge_drift_check`` capsule. Nothing here builds a capsule, assembles
a bundle, or seals a verdict -- that is all the harness's job. The ONLY thing
this module owns is the consistency comparison itself.

**Where the serving fields live.** Each capsule the mesh/tau2 emitter seals
carries its serving provenance under ``model_attestation`` -- the top-level
``model_id``/``provider`` and the ``compute_attestation`` sub-block (mesh
``serving_provenance``: ``gpu``/``vram_bytes``/``is_soc``/``hostname``/
``served_by_node_id`` plus ``model``/``architecture``/``parameter_size``; the
tau2 shape's ``served_by``/``model_id``; and the exchange builder's
``hardware``/``quant``/``runtime``). This module reads them wherever they
appear -- ``compute_attestation`` first, then the ``model_attestation`` top
level -- and never invents a value that isn't there.

**Two field classes, honest three-state.**

- *Hardware-invariant* fields (``gpu``/``vram_bytes``/``is_soc``/
  ``served_by_node_id``/``hostname``): a machine's hardware does not change
  between exchanges, and ``served_by_node_id`` changing means it is not the
  same signer. Any change across the range is a FLAG.
- *Model/quant* fields (``model``/``model_id``/``architecture``/
  ``parameter_size``/``quant``): a model change is not necessarily fraud, but
  it is an attributable, DISCLOSED delta -- surfaced as ``changed``, never a
  silent pass.

Every field resolves to exactly one of three states, never a fabricated
"consistent":

- ``consistent`` -- present in every capsule that carries it, all equal.
- ``changed``    -- present in >1 capsule with >1 distinct value.
- ``absent``     -- carried by NO capsule in the range (honestly unknown,
  never a false "consistent"; a field present in some but missing in others
  is reported as ``changed`` on the ``present_in`` axis is NOT claimed --
  see ``partial`` below).

The scorer's single ``label`` (from the prompt's closed ``label_set``) is the
range verdict: ``consistent`` only if every hardware-invariant field that is
present is equal across the range AND no field is ``changed``; ``changed`` if
any field changed (a hardware change is called out by name in the rationale
and the ``flagged_hardware`` list); ``absent`` only when the range carries no
comparable serving field at all. Model-only changes still resolve to
``changed`` (the disclosed delta) -- the ``flagged_hardware`` list is what
separates "a machine swapped hardware / signer" from "a node disclosed a new
model on the same box".

**Deterministic.** Operates ONLY over the declared capsule range handed to it
(carried in ``evidence.evidence_text`` as canonical JSON -- the plaintext
seam ``scorer.py`` reserves for exactly this, "deliberately never a capsule
field"). No wall-clock, no external state, no ledger re-scan: the same range
in always yields the same ``ScoreResult`` out, so the harness's own drift
re-run is meaningful (honoring the ``wall_clock_reserved_field`` discipline
the fold engine enforces -- a judgment reads only its declared inputs).
"""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from agent_action_capsule.canonical import json_digest

from ..errors import SCORER_LABEL_NOT_IN_LABEL_SET, JudgeError
from ..prompt import JudgePromptDefinition
from ..scorer import JudgeEvidence, ScoreResult

__all__ = [
    "ServingConsistencyScorer",
    "FieldConsistency",
    "ServingRangeVerdict",
    "HARDWARE_INVARIANT_FIELDS",
    "MODEL_FIELDS",
    "LABEL_CONSISTENT",
    "LABEL_CHANGED",
    "LABEL_ABSENT",
    "serving_evidence_text",
    "extract_serving_view",
]

# The label set this scorer emits -- the prompt's own ``label_set`` MUST be
# exactly these three (checked at score() time), so the judgment capsule's
# closed-label-set invariant carries the honest three-state through verbatim.
LABEL_CONSISTENT = "consistent"
LABEL_CHANGED = "changed"
LABEL_ABSENT = "absent"

# A machine's hardware does not change between exchanges; ``served_by_node_id``
# changing means it is not the same signer. Any change here is a flag.
HARDWARE_INVARIANT_FIELDS: tuple[str, ...] = (
    "served_by_node_id",
    "served_by",
    "gpu",
    "vram_bytes",
    "is_soc",
    "hostname",
    "hardware",
)

# A model/quant change is an attributable, disclosed delta -- reported, never
# silently passed, but not a hardware flag on its own.
MODEL_FIELDS: tuple[str, ...] = (
    "model",
    "model_id",
    "architecture",
    "parameter_size",
    "quant",
)

_ALL_FIELDS: tuple[str, ...] = HARDWARE_INVARIANT_FIELDS + MODEL_FIELDS


def _serving_view(capsule: Mapping[str, Any]) -> dict[str, Any]:
    """Pull the comparable serving fields out of one capsule.

    ``compute_attestation`` wins over the ``model_attestation`` top level when
    both carry the same key (the compute block is the fine-grained serving
    record); a field carried by neither is simply absent from the view, never
    defaulted -- absence must survive as absence for the three-state to be
    honest."""
    attestation = capsule.get("model_attestation") or {}
    compute = attestation.get("compute_attestation") or {}
    view: dict[str, Any] = {}
    for name in _ALL_FIELDS:
        if name in compute:
            view[name] = compute[name]
        elif name in attestation:
            view[name] = attestation[name]
    return view


def extract_serving_view(capsule: Mapping[str, Any]) -> dict[str, Any]:
    """Public helper: the comparable serving fields of one capsule (see
    ``_serving_view``). Callers assembling a range for
    ``serving_evidence_text`` do not have to know the field layout."""
    return _serving_view(capsule)


def serving_evidence_text(capsules: Sequence[Mapping[str, Any]]) -> str:
    """Canonical, deterministic evidence text for a range of a node's
    capsules -- the plaintext an ``JudgeEvidence`` carries into this scorer.

    Only the comparable serving view of each capsule is included (never raw
    message content -- H2: content never enters a capsule, and it need not
    enter the evidence either), in append order, so the same range always
    produces byte-identical evidence text and therefore a deterministic
    verdict. The order is preserved, not sorted: "before vs now" is an
    ordered claim."""
    views = [_serving_view(c) for c in capsules]
    return json.dumps({"serving_range": views}, separators=(",", ":"), sort_keys=True)


def _parse_range(evidence_text: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(evidence_text)
    except (ValueError, TypeError) as exc:
        raise JudgeError(
            SCORER_LABEL_NOT_IN_LABEL_SET,
            "ServingConsistencyScorer evidence_text must be JSON produced by "
            f"serving_evidence_text(); got un-parseable text ({exc})",
        ) from exc
    views = data.get("serving_range") if isinstance(data, dict) else None
    if not isinstance(views, list) or not views:
        raise JudgeError(
            SCORER_LABEL_NOT_IN_LABEL_SET,
            "ServingConsistencyScorer evidence_text carries no 'serving_range' list -- "
            "assemble it with serving_evidence_text() over the node's capsule range",
        )
    return [v if isinstance(v, dict) else {} for v in views]


@dataclass(frozen=True)
class FieldConsistency:
    """One serving field's verdict across the range."""

    field: str
    state: str  # LABEL_CONSISTENT | LABEL_CHANGED | LABEL_ABSENT
    is_hardware: bool
    present_count: int
    range_size: int
    values: tuple[Any, ...]  # distinct values in first-seen order (empty if absent)

    @property
    def partial(self) -> bool:
        """Present in SOME capsules but not all -- an honest caveat that never
        upgrades an ``absent`` or a single-value field to a false
        ``consistent`` across the whole range."""
        return 0 < self.present_count < self.range_size

    def to_detail(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "state": self.state,
            "is_hardware": self.is_hardware,
            "present_count": self.present_count,
            "range_size": self.range_size,
            "distinct_values": [json.dumps(v, sort_keys=True) for v in self.values],
            "partial": self.partial,
        }


@dataclass(frozen=True)
class ServingRangeVerdict:
    """The full per-field breakdown behind the scorer's single label -- the
    ``changed(field=...)`` detail the honest three-state promises. Attached to
    the ``ScoreResult`` rationale (digested onto the judgment capsule), and
    re-derivable from the same range."""

    label: str
    range_size: int
    fields: tuple[FieldConsistency, ...]
    flagged_hardware: tuple[str, ...]  # hardware-invariant fields that CHANGED
    changed_model: tuple[str, ...]  # model/quant fields that changed (disclosed delta)

    def to_detail(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "range_size": self.range_size,
            "flagged_hardware": list(self.flagged_hardware),
            "changed_model": list(self.changed_model),
            "fields": [f.to_detail() for f in self.fields],
        }

    def rationale(self) -> str:
        if self.flagged_hardware:
            head = "HARDWARE CHANGED across range: " + ", ".join(
                f"{f.field} {list(f.values)!r}" for f in self.fields if f.field in self.flagged_hardware
            )
        elif self.changed_model:
            head = "model/quant changed (disclosed delta): " + ", ".join(
                f"{f.field} {list(f.values)!r}" for f in self.fields if f.field in self.changed_model
            )
        else:
            comparable = [f for f in self.fields if f.state != LABEL_ABSENT]
            head = (
                f"serving consistent across {self.range_size} capsule(s): "
                + ", ".join(f.field for f in comparable)
                if comparable
                else "no comparable serving field present in the range"
            )
        return head + f" | verdict={self.label} | range={self.range_size}"


def _distinct_in_order(values: list[Any]) -> list[Any]:
    """Distinct values in first-seen order, comparing by a canonical key so
    two structurally-equal dicts/lists count as one value (order preserved --
    "before vs now" is ordered)."""
    seen: list[str] = []
    out: list[Any] = []
    for v in values:
        # Scalars compare by their canonical JSON; containers by a stable
        # digest -- either way, structural equality is what "the value changed"
        # means, never object identity.
        key = json.dumps(v, sort_keys=True) if isinstance(v, (str, int, float, bool)) or v is None else json_digest(v)
        if key not in seen:
            seen.append(key)
            out.append(v)
    return out


def _field_consistency(name: str, views: list[dict[str, Any]]) -> FieldConsistency:
    present = [v[name] for v in views if name in v]
    distinct = _distinct_in_order(present)
    range_size = len(views)
    if not present:
        state = LABEL_ABSENT
    elif len(distinct) > 1:
        state = LABEL_CHANGED
    else:
        state = LABEL_CONSISTENT
    return FieldConsistency(
        field=name,
        state=state,
        is_hardware=name in HARDWARE_INVARIANT_FIELDS,
        present_count=len(present),
        range_size=range_size,
        values=tuple(distinct),
    )


def score_serving_range(views: list[dict[str, Any]]) -> ServingRangeVerdict:
    """The core comparison -- pure over the declared range, no capsule, no
    ledger, no clock. Exposed for direct unit testing and re-derivation."""
    fields = tuple(_field_consistency(name, views) for name in _ALL_FIELDS)
    flagged_hardware = tuple(f.field for f in fields if f.is_hardware and f.state == LABEL_CHANGED)
    changed_model = tuple(f.field for f in fields if not f.is_hardware and f.state == LABEL_CHANGED)

    any_changed = any(f.state == LABEL_CHANGED for f in fields)
    any_comparable = any(f.state != LABEL_ABSENT for f in fields)
    if any_changed:
        label = LABEL_CHANGED
    elif any_comparable:
        label = LABEL_CONSISTENT
    else:
        label = LABEL_ABSENT

    return ServingRangeVerdict(
        label=label,
        range_size=len(views),
        fields=fields,
        flagged_hardware=flagged_hardware,
        changed_model=changed_model,
    )


@dataclass(frozen=True)
class ServingConsistencyScorer:
    """A deterministic serving/hardware-consistency ``Scorer``.

    ``model_id`` names this scorer's own identity in the judge pin (it is a
    deterministic rule, not a model -- but the pin slot is the same). The
    ``label_set`` of the prompt handed to ``score()`` MUST be exactly the
    three-state set (``consistent``/``changed``/``absent``); anything else is
    rejected rather than silently coerced."""

    model_id: str = "serving-consistency/deterministic"

    def score(self, *, evidence: JudgeEvidence, prompt: JudgePromptDefinition) -> ScoreResult:
        label_set = set(prompt.label_set)
        required = {LABEL_CONSISTENT, LABEL_CHANGED, LABEL_ABSENT}
        if label_set != required:
            raise JudgeError(
                SCORER_LABEL_NOT_IN_LABEL_SET,
                f"ServingConsistencyScorer requires prompt.label_set == {sorted(required)}; "
                f"got {sorted(label_set)}",
            )
        views = _parse_range(evidence.evidence_text)
        verdict = score_serving_range(views)
        # Confidence is deterministic and honest: full certainty for a clean
        # comparison; a partial-coverage field lowers it (we saw a value in
        # some capsules but not all), never faked to 1.0.
        any_partial = any(f.partial for f in verdict.fields if f.state != LABEL_ABSENT)
        confidence = 1.0 if not any_partial else 0.75
        return ScoreResult(
            label=verdict.label,
            confidence=confidence,
            model_id=self.model_id,
            rationale=verdict.rationale(),
        )
