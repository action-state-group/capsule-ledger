# SPDX-License-Identifier: Apache-2.0
"""The dual compiler (design §0/§2.1, build plan Phase 2 item 1): one
``Declaration`` (D), compiled **forward** into ``P`` (a wicket config for
``guards/checks/plan_containment.py``, existing machinery -- this module is
wiring, not a new forward-check engine) and **backward** into ``F`` (a
fold), with the binding between them sealed as the compilation record C
(``compilation_record.build_compilation_record_capsule``).

**The two refusal vocabularies never conflate here.** ``effect_model.
compile_effect_claim`` REFUSING an effect claim is a *compiler* refusal
(design §2.2: "this statement cannot be mapped") -- it produces a
``ForwardCompilation``/``BackwardCompilation`` pair with no ``plan``/
``fold`` and no wicket wiring at all. A *forward* refusal ("the guard
declined to dispatch") is a live decision ``guards/engine.py`` makes at act
time against an already-compiled plan; this module never emits one and
never could -- it runs at declare time, before any action exists.

**Uniform sealing, so drift is detectable everywhere, not just on the happy
path** (design §2.1: "a receipt carrying P without C cannot tell a relying
party whether the report describes the rule that was actually enforced").
Every compiled declaration seals a C, whether or not it produced a real
``PlanDefinition``/``FoldDefinition`` -- ``ForwardCompilation.digest()``/
``BackwardCompilation.digest()`` commit to the VERDICT plus whichever
artifact (if any) backs it, so a compiler that starts silently swapping an
``UNAVAILABLE-MODEL-REQUIRED`` verdict for a plan-backed one (or vice
versa) changes the digest and is caught by ``verify_compilation_record``,
not just a compiler that swaps one real plan for another.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_action_capsule.canonical import json_digest

from ..folds.definition import FilterClause, FoldDefinition, ReadField, Reduce
from ..guards.plan import PlanDefinition
from ..guards.signing import Signer
from ..guards.wickets.definition import WicketDefinition
from .effect_model import EFFECT_CLAIMS, compile_effect_claim
from .precondition import PreconditionPrimitive
from .vocabulary import VerdictPair

__all__ = [
    "COMPILER_ID",
    "COMPILER_VERSION",
    "CompilerError",
    "GatedPrecondition",
    "Declaration",
    "ForwardCompilation",
    "BackwardCompilation",
    "CompiledDeclaration",
    "DriftResult",
    "compile_declaration",
    "seal_compilation_record",
    "verify_compilation_record",
    "wicket_entry_for",
]

COMPILER_ID = "capsule_ledger.compiler"
COMPILER_VERSION = "0.1.0"


class CompilerError(ValueError):
    """A declaration cannot be compiled -- malformed input, not a refusal.
    A refusal (design §2.2) is a successful compile whose verdict is
    REFUSED; this is raised only when the declaration itself is unusable
    (e.g. no allowed_actions and no model-judgment flag -- nothing to
    forward-compile against and no reason given for why not)."""


@dataclass(frozen=True)
class GatedPrecondition:
    """One precondition primitive, bound to the specific allowed action it
    gates -- ``guards.plan.PlanPrecondition`` is per-action, so a
    declaration's precondition list must say which action each primitive
    applies to, not just which primitive kind it is."""

    action: str
    primitive: PreconditionPrimitive


@dataclass(frozen=True)
class Declaration:
    """D: one outcome statement, written once. This is the compiler's own
    input shape -- deliberately smaller than ``packs.schema.Outcome``
    (the pack-level, already-digested declaration shape P1 shipped): a
    pack author's ``Outcome`` is what this module would be handed by a
    loader wiring outcomes into the compiler (a later, separate task); this
    dataclass is what actually drives ``compile_declaration`` today.

    ``requires_model_judgment=True`` is the compiler's explicit, honest
    admission that a statement has no closed-vocabulary decomposition --
    design §2.2's canonical case, *"act in good faith"*: no precondition
    primitive can express it, so it is never silently offered forward.
    """

    outcome_id: str
    statement: str
    effect_claim: str | None = None
    preconditions: tuple[GatedPrecondition, ...] = ()
    allowed_actions: tuple[str, ...] = ()
    binding: dict[str, Any] = field(default_factory=dict)
    window: str | None = None
    requires_model_judgment: bool = False
    cedar_policy_digest: str | None = None

    def __post_init__(self) -> None:
        if self.effect_claim is not None and self.effect_claim not in EFFECT_CLAIMS:
            raise CompilerError(f"effect_claim must be one of {sorted(EFFECT_CLAIMS)}; got {self.effect_claim!r}")
        for gated in self.preconditions:
            if gated.action not in self.allowed_actions:
                raise CompilerError(
                    f"precondition gates action {gated.action!r}, which is not in allowed_actions "
                    f"{self.allowed_actions}"
                )


@dataclass(frozen=True)
class ForwardCompilation:
    verdict: str
    plan: PlanDefinition | None = None
    refusal_reason_code: str | None = None

    def canonical_dict(self) -> dict:
        out: dict[str, Any] = {"verdict": self.verdict}
        if self.plan is not None:
            out["plan"] = self.plan.canonical_dict()
        if self.refusal_reason_code is not None:
            out["refusal_reason_code"] = self.refusal_reason_code
        return out

    def digest(self) -> str:
        return json_digest(self.canonical_dict())


@dataclass(frozen=True)
class BackwardCompilation:
    verdict: str
    fold: FoldDefinition | None = None
    refusal_reason_code: str | None = None

    def canonical_dict(self) -> dict:
        out: dict[str, Any] = {"verdict": self.verdict}
        if self.fold is not None:
            out["fold"] = self.fold.canonical_dict()
        if self.refusal_reason_code is not None:
            out["refusal_reason_code"] = self.refusal_reason_code
        return out

    def digest(self) -> str:
        return json_digest(self.canonical_dict())


@dataclass(frozen=True)
class CompiledDeclaration:
    outcome_id: str
    forward: ForwardCompilation
    backward: BackwardCompilation

    @property
    def verdict_pair(self) -> VerdictPair:
        return VerdictPair(forward=self.forward.verdict, backward=self.backward.verdict)

    @property
    def over_breadth(self) -> int | None:
        """The admitted-action-space measure (design §2.5), sealed at
        digest-freeze on the compiled plan itself -- ``None`` when no plan
        was compiled (there is no action space to measure). Breadth, not
        satisfiability -- see ``PlanDefinition.admitted_action_space_size``'s
        own docstring for what this number does not claim."""
        return None if self.forward.plan is None else self.forward.plan.admitted_action_space_size()


def _slug(outcome_id: str) -> str:
    return outcome_id.split("/")[0].replace(".", "_")


def _fold_for_declaration(d: Declaration) -> FoldDefinition:
    """The backward compile of a precondition-decomposable declaration: an
    attainment-style count of how often this declaration's admitted action
    set was actually executed, grouped by developer -- the same shape as
    the hand-written ``actions.executed_count`` catalog fold, now derived
    from D instead of hand-authored per pack. ``action_class`` is the read
    path (not ``verb`` -- a bare verb is never written onto a sealed
    capsule's disclosed ``asg_payload``; ``action_class`` is, per
    ``guards/capsule.py``'s ``_payload_extension``), so the fold only
    partitions as finely as what a stranger reading the ledger can actually
    see.
    """
    action_classes = sorted({b for b in (d.binding.get("action_class"),) if b is not None})
    reads = (
        ReadField(path="developer", erasure_class="commitment-ok"),
        ReadField(path="disposition.verdict_class", erasure_class="commitment-ok"),
    )
    filters = [FilterClause(field="disposition.verdict_class", op="eq", value="executed")]
    if action_classes:
        reads = reads + (ReadField(path="asg_payload.action_class", erasure_class="commitment-ok"),)
        filters.append(FilterClause(field="asg_payload.action_class", op="in", value=action_classes))
    return FoldDefinition(
        fold_id=f"compiler.{_slug(d.outcome_id)}.attainment/1.0.0",
        reads=reads,
        filter=tuple(filters),
        key="developer",
        reduce=Reduce(reducer="count"),
        emit=f"{d.outcome_id}.count",
    )


def _model_assisted_fold(d: Declaration) -> FoldDefinition:
    """Backward compile for a model-judgment statement: still a real,
    digestible fold (a judgment-count, not an attainment-count -- design
    §2.2: the judge only ever records) -- never ``None`` merely because
    forward is unavailable. A statement is only ``fold=None`` when it is
    REFUSED (design §2.2's second refusal vocabulary: nothing to evaluate,
    forward or backward, at all)."""
    return FoldDefinition(
        fold_id=f"compiler.{_slug(d.outcome_id)}.judgment_count/1.0.0",
        reads=(
            ReadField(path="developer", erasure_class="commitment-ok"),
            ReadField(path="disposition.verdict_class", erasure_class="commitment-ok"),
        ),
        key="developer",
        reduce=Reduce(reducer="count"),
        emit=f"{d.outcome_id}.judgment_count",
    )


def compile_declaration(d: Declaration) -> CompiledDeclaration:
    """The dual compile. Branch order matters and mirrors design §2.2's own
    priority: an undecomposable effect claim REFUSES outright (it is never
    "sort of" forward-checkable); only once that is clear does the
    model-judgment/precondition split decide what P and F actually are."""
    if d.effect_claim is not None:
        compiled_claim = compile_effect_claim(d.effect_claim)
        if compiled_claim.verdict.forward == "REFUSED":
            return CompiledDeclaration(
                outcome_id=d.outcome_id,
                forward=ForwardCompilation(verdict="REFUSED", refusal_reason_code=compiled_claim.refusal_reason_code),
                backward=BackwardCompilation(
                    verdict="REFUSED", refusal_reason_code=compiled_claim.refusal_reason_code
                ),
            )

    if d.requires_model_judgment:
        # design §2.2, canonical case: MODEL-ASSISTED is never offered
        # forward -- the judge is never in the enforcement path.
        return CompiledDeclaration(
            outcome_id=d.outcome_id,
            forward=ForwardCompilation(verdict="UNAVAILABLE-MODEL-REQUIRED"),
            backward=BackwardCompilation(verdict="MODEL-ASSISTED", fold=_model_assisted_fold(d)),
        )

    if not d.allowed_actions:
        raise CompilerError(
            f"declaration {d.outcome_id!r} has no allowed_actions and is not flagged "
            "requires_model_judgment -- nothing to compile forward against"
        )

    plan_preconditions = tuple(
        gated.primitive.to_plan_precondition(action=gated.action) for gated in d.preconditions
    )
    binding = dict(d.binding)
    if d.cedar_policy_digest is not None:
        binding["cedar_policy_digest"] = d.cedar_policy_digest
    plan = PlanDefinition(
        outcome_id=d.outcome_id,
        allowed_actions=d.allowed_actions,
        preconditions=plan_preconditions,
        binding=binding,
        window=d.window,
    )
    fold = _fold_for_declaration(d)
    return CompiledDeclaration(
        outcome_id=d.outcome_id,
        forward=ForwardCompilation(verdict="DETERMINISTIC", plan=plan),
        backward=BackwardCompilation(verdict="DETERMINISTIC", fold=fold),
    )


def wicket_entry_for(plan: PlanDefinition, *, wicket_id: str) -> WicketDefinition:
    """P *is* a wicket config (design/build-plan Phase 2 item 1: ``check:
    plan_containment, config: {outcome_id, allowed_actions, preconditions,
    binding, window}``). This is the literal wrapping a pack author pastes
    into ``constraints:`` -- ``plan.definition_digest()`` is unaffected by
    it either way (``guards/plan.py``'s own docstring)."""
    return WicketDefinition(wicket_id=wicket_id, check="plan_containment", config=plan.canonical_dict())


def seal_compilation_record(
    compiled: CompiledDeclaration,
    *,
    d_digest: str,
    operator: str,
    developer: str,
    signer: Signer,
    d_prev_digest: str | None = None,
    replay_report_digest: str | None = None,
    timestamp: str | None = None,
) -> dict:
    from .compilation_record import build_compilation_record_capsule

    return build_compilation_record_capsule(
        d_digest=d_digest,
        p_digest=compiled.forward.digest(),
        f_digest=compiled.backward.digest(),
        compiler_id=COMPILER_ID,
        compiler_version=COMPILER_VERSION,
        operator=operator,
        developer=developer,
        signer=signer,
        d_prev_digest=d_prev_digest,
        replay_report_digest=replay_report_digest,
        timestamp=timestamp,
        action_id=f"compiler.compilation_record/{compiled.outcome_id}",
    )


@dataclass(frozen=True)
class DriftResult:
    """The C check (design/build-plan Phase 2 acceptance line: "mutate the
    compiler so P and F derive from different declarations and show the C
    check goes RED. If that mutant passes, C is decoration.")."""

    drifted: bool
    p_drifted: bool
    f_drifted: bool
    recomputed_d_digest: str
    sealed_d_digest: str


def verify_compilation_record(sealed_detail: dict, *, recompiled: CompiledDeclaration, d_digest: str) -> DriftResult:
    """Recompute P's and F's digests from a fresh compile of D and compare
    against what a sealed compilation record C actually claims. This is the
    ONLY thing that makes C more than decoration: a verifier who did not
    trust the original compile run can hold D, recompile it themselves
    (``compile_declaration``), and check the two halves still bind to the
    SAME declaration -- not merely that each half is internally
    well-formed."""
    p_drifted = sealed_detail["p_digest"] != recompiled.forward.digest()
    f_drifted = sealed_detail["f_digest"] != recompiled.backward.digest()
    return DriftResult(
        drifted=p_drifted or f_drifted,
        p_drifted=p_drifted,
        f_drifted=f_drifted,
        recomputed_d_digest=d_digest,
        sealed_d_digest=sealed_detail["d_digest"],
    )
