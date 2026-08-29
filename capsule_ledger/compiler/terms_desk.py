# SPDX-License-Identifier: Apache-2.0
"""The terms-desk compile profile (terms-to-report design §1/§9): a
**report-only** profile of the existing outcome compiler that compiles a
confirmed terms document ``T`` -- many named terms, not one outcome -- into
per-term ``A_i``/``F_i``/``J_i`` (and ``P_i`` only where the term's forward
verdict is DETERMINISTIC), sealed as a compilation record ``C`` that chains
via ``t_prev_digest`` the same way ``compilation_record.py``'s single-
declaration ``C`` chains via ``d_prev_digest``.

**Additive, not a fork.** Every real compile decision -- whether a
statement is DETERMINISTIC, MODEL-ASSISTED, or REFUSED, and what its plan
(``P``) and fold (``F``) actually are -- is made by ``compile.
compile_declaration`` and ``setup.compile_bridge.compiled_declaration_for``,
called here, never reimplemented. Pack-first terms (the common case: an
adopted/narrowed catalog row, census-graded by ``setup.propose`` and
confirmed by ``setup.confirm``) arrive as a ``StoredCandidate`` and are
compiled via ``compiled_declaration_for``. A term whose forward verdict is
inherently non-deterministic (MODEL-ASSISTED, judged) has no ``Candidate``
kind in ``setup/candidates.py`` yet -- extending that catalog with a judged
kind is future work, flagged in the epic report, not attempted here -- so
that one term shape is built directly from a ``compile.Declaration`` with
``requires_model_judgment=True``, still compiled by the same
``compile_declaration``.

**Two new primitives this profile genuinely adds** (design §9: "what is
genuinely new"), because nothing in the compiler represents them yet:

- ``ApplicabilitySpec`` -- ``A_i``, the denominator rule: which units a
  term even applies to (design §1's "unit of assessment" + "applicability
  predicate"). Built from ``folds.definition.FilterClause``, the same
  bounded-predicate vocabulary a fold's own filter already uses -- not a
  second filter language.
- ``JudgeOrRuleSpec`` -- ``J_i``: a judge spec (verdict schema + prompt
  digest + model pin + sampling) for a MODEL-ASSISTED term, or the
  deterministic rule, digest-pinned either way (design §1). For a
  DETERMINISTIC/WITH-INSTRUMENTATION/MANUAL term the "rule" is exactly
  what the compiled fold already encodes, so its digest is pinned to
  ``f_digest`` rather than re-describing the rule a second way.

**The P/F lesson, closed on both holes here too** (design §1, §9):
``verify_terms_compilation_record`` (1) recomputes ``t_digest`` and every
per-term digest from the confirmed ``TermsDocument`` itself, never merely
checking the sealed record's own internal consistency, and (2) for every
term whose forward verdict is DETERMINISTIC (so a real plan exists
alongside a real fold), independently confirms the two agree on which
action classes they govern -- digest equality proves co-derivation, not
correspondence, which is exactly the bug class the compiler's own P/F
non-correspondence fix (a separate, in-flight branch) exists to close;
this profile does not import that fix, so it re-asserts the same coherence
property for its own sealed rows rather than silently trusting digest
equality alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_action_capsule.canonical import json_digest
from agent_action_capsule.contracts import is_hex64

from ..folds.definition import FilterClause
from ..folds.engine import EvaluationTrace, evaluate_all
from ..folds.paths import get_path
from ..guards.capsule import build_event_capsule
from ..guards.signing import Signer
from ..packs.schema import MODE_VALUES, TIER_VALUES
from ..setup.compile_bridge import compiled_declaration_for
from ..setup.declarations import StoredCandidate
from .compile import (
    COMPILER_ID,
    COMPILER_VERSION,
    CompiledDeclaration,
    CompilerError,
    Declaration,
    compile_declaration,
)

__all__ = [
    "EVENT_TERMS_COMPILATION_RECORD",
    "APPLICABILITY_UNITS",
    "JUDGE_OR_RULE_KINDS",
    "ApplicabilitySpec",
    "JudgeOrRuleSpec",
    "TermDeclaration",
    "TermsDocument",
    "CompiledTerm",
    "TermDriftEntry",
    "TermsDriftResult",
    "compile_term",
    "compile_terms_document",
    "compiled_term_digest",
    "build_terms_compilation_record_capsule",
    "verify_terms_compilation_record",
    "evaluate_term_fold",
]

EVENT_TERMS_COMPILATION_RECORD = "compiler.terms_compilation_record"

# design §1's "unit of assessment" -- what a verdict attaches to.
APPLICABILITY_UNITS = frozenset({"turn", "conversation", "case"})

JUDGE_OR_RULE_KINDS = frozenset({"judge", "deterministic_rule"})


@dataclass(frozen=True)
class ApplicabilitySpec:
    """``A_i``: which units this term even applies to -- the denominator
    rule (design §1). A bounded predicate over the same
    ``FilterClause`` vocabulary a fold's own filter already uses, not a
    second, driftable filter language."""

    unit: str
    filters: tuple[FilterClause, ...] = ()

    def __post_init__(self) -> None:
        if self.unit not in APPLICABILITY_UNITS:
            raise CompilerError(f"unit must be one of {sorted(APPLICABILITY_UNITS)}; got {self.unit!r}")

    def canonical_dict(self) -> dict:
        out: dict[str, Any] = {"unit": self.unit}
        if self.filters:
            out["filters"] = [{"field": f.field, "op": f.op, "value": f.value} for f in self.filters]
        return out

    def digest(self) -> str:
        return json_digest(self.canonical_dict())


@dataclass(frozen=True)
class JudgeOrRuleSpec:
    """``J_i`` (design §1): "verdict schema + prompt digest + model pin +
    sampling params, or the deterministic rule, digest-pinned either way."
    ``kind="judge"`` for a MODEL-ASSISTED term (fields confirmed by a human
    at T1, never recomputed); ``kind="deterministic_rule"`` for every other
    executor class, where ``rule_digest`` is pinned to the compiled fold's
    own digest (``compile_term`` sets this automatically -- the rule IS
    what the fold already encodes, so this never re-describes it a second,
    driftable way)."""

    kind: str
    verdict_schema: tuple[str, ...]
    model_id: str | None = None
    model_version: str | None = None
    prompt_digest: str | None = None
    sampling: dict[str, Any] | None = None
    rule_digest: str | None = None
    rule_kind: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in JUDGE_OR_RULE_KINDS:
            raise CompilerError(f"kind must be one of {sorted(JUDGE_OR_RULE_KINDS)}; got {self.kind!r}")
        if not self.verdict_schema:
            raise CompilerError(
                "verdict_schema must be non-empty (design §1: boolean, closed enum, or bounded scalar; never free-text)"
            )
        if self.kind == "judge":
            if not self.model_id or not self.prompt_digest:
                raise CompilerError("a judge spec requires model_id and prompt_digest")
            if self.rule_digest is not None or self.rule_kind is not None:
                raise CompilerError("rule_digest/rule_kind are only set on a kind='deterministic_rule' spec")
        else:
            if not self.rule_digest:
                raise CompilerError("a deterministic_rule spec requires rule_digest")
            if (
                self.model_id is not None
                or self.model_version is not None
                or self.prompt_digest is not None
                or self.sampling is not None
            ):
                raise CompilerError(
                    "model_id/model_version/prompt_digest/sampling are only set on a kind='judge' spec"
                )

    def canonical_dict(self) -> dict:
        out: dict[str, Any] = {"kind": self.kind, "verdict_schema": list(self.verdict_schema)}
        if self.kind == "judge":
            out["model_id"] = self.model_id
            if self.model_version is not None:
                out["model_version"] = self.model_version
            out["prompt_digest"] = self.prompt_digest
            if self.sampling:
                out["sampling"] = dict(self.sampling)
        else:
            out["rule_digest"] = self.rule_digest
            if self.rule_kind is not None:
                out["rule_kind"] = self.rule_kind
        return out

    def digest(self) -> str:
        return json_digest(self.canonical_dict())


def _declaration_canonical_dict(d: Declaration) -> dict:
    """A minimal canonical form for ``compile.Declaration`` -- only needed
    for the direct-declaration (MODEL-ASSISTED) path below, since D's
    pack-first path already has one (``setup.declarations.candidate_digest``).
    Not exhaustive of every field a forward-compiled ``Declaration`` could
    carry (preconditions/bindings are real fields, included for
    completeness); a MODEL-ASSISTED declaration never sets ``allowed_actions``
    (the judge is never in the enforcement path), so those fields are
    empty in practice."""
    out: dict[str, Any] = {
        "outcome_id": d.outcome_id,
        "statement": d.statement,
        "requires_model_judgment": d.requires_model_judgment,
    }
    if d.effect_claim is not None:
        out["effect_claim"] = d.effect_claim
    if d.allowed_actions:
        out["allowed_actions"] = list(d.allowed_actions)
    if d.binding:
        out["binding"] = d.binding
    if d.window is not None:
        out["window"] = d.window
    if d.cedar_policy_digest is not None:
        out["cedar_policy_digest"] = d.cedar_policy_digest
    if d.preconditions:
        out["preconditions"] = [
            {"action": g.action, "kind": g.primitive.kind, "params": g.primitive.params}
            for g in d.preconditions
        ]
    return out


@dataclass(frozen=True)
class TermDeclaration:
    """One row of the confirmed terms document ``T`` (design §1). Exactly
    one of ``stored``/``declaration`` is set:

    - ``stored`` -- the pack-first path (design §1 [rev3]): a
      ``StoredCandidate`` already census-graded by ``setup.propose`` and
      adopted/narrowed/refused by ``setup.confirm`` (T1 or T4). Compiled
      via ``compiled_declaration_for`` -- the human-confirmed verdict pair
      is reused verbatim, never recomputed against a possibly-different
      corpus snapshot.
    - ``declaration`` -- the direct path: a ``compile.Declaration`` built
      by hand and compiled via ``compile_declaration``. This is the only
      path available for a term whose forward verdict is inherently
      MODEL-ASSISTED (``setup/candidates.py`` has no judged ``Candidate``
      kind yet -- flagged as follow-up in the epic report), and is also
      available for any other declaration shape the pack-first
      attainment/offer-response/decision templates don't cover.

    Whether ``judge_spec`` is required is decided by ``compile_term`` from
    the term's *compiled* backward verdict, not by which path built it --
    a term is never asked to pre-declare what the compiler will conclude.

    ``tier`` ([ldg-bj-tier-field], backward-judge design §8.2) says whether
    this term gates a session's job-success (``"must_have"``) or is reported
    without gating (``"informational"``, the default) -- mirrors ``packs.
    schema.Outcome.tier``; see ``TIER_VALUES``.

    ``mode`` ([ldg-bp-mode-tag], standard-outcome-pack design §3) says which
    of the seven ways this term is judged, default ``"structural"`` --
    mirrors ``packs.schema.Outcome.mode``; see ``MODE_VALUES``.
    """

    term_id: str
    statement: str
    clause_ref: str | None
    applicability: ApplicabilitySpec
    verdict_schema: tuple[str, ...]
    stored: StoredCandidate | None = None
    declaration: Declaration | None = None
    judge_spec: JudgeOrRuleSpec | None = None
    rule_kind: str | None = None
    tier: str = "informational"
    mode: str = "structural"

    def __post_init__(self) -> None:
        if not self.verdict_schema:
            raise CompilerError(
                f"term {self.term_id!r} must confirm a non-empty verdict_schema "
                "(design §1: boolean, closed enum, or bounded scalar; never free-text)"
            )
        if (self.stored is None) == (self.declaration is None):
            raise CompilerError(f"term {self.term_id!r} must set exactly one of stored/declaration")
        if self.tier not in TIER_VALUES:
            raise CompilerError(
                f"term {self.term_id!r}.tier={self.tier!r} must be one of {sorted(TIER_VALUES)}, or omitted "
                "(defaults to 'informational')"
            )
        if self.mode not in MODE_VALUES:
            raise CompilerError(
                f"term {self.term_id!r}.mode={self.mode!r} must be one of {sorted(MODE_VALUES)}, or omitted "
                "(defaults to 'structural')"
            )

        if self.stored is not None:
            if self.stored.candidate.outcome_id != self.term_id:
                raise CompilerError(
                    f"term_id {self.term_id!r} does not match stored candidate outcome_id "
                    f"{self.stored.candidate.outcome_id!r}"
                )
            if self.stored.acceptance_state == "proposed":
                raise CompilerError(
                    f"term {self.term_id!r} is only 'proposed' -- design §1: 'everything after T1 is "
                    "deterministic' presumes T1/T4 confirmation has already happened"
                )
        else:
            assert self.declaration is not None
            if self.declaration.outcome_id != self.term_id:
                raise CompilerError(
                    f"term_id {self.term_id!r} does not match declaration outcome_id {self.declaration.outcome_id!r}"
                )

        if self.judge_spec is not None:
            if self.judge_spec.kind != "judge":
                raise CompilerError(f"term {self.term_id!r}'s judge_spec must be of kind='judge'")
            if self.judge_spec.verdict_schema != self.verdict_schema:
                raise CompilerError(
                    f"term {self.term_id!r}'s judge_spec.verdict_schema {self.judge_spec.verdict_schema} "
                    f"does not match the term's own confirmed verdict_schema {self.verdict_schema}"
                )


def _term_to_canonical_dict(t: TermDeclaration) -> dict:
    out: dict[str, Any] = {
        "term_id": t.term_id,
        "statement": t.statement,
        "applicability": t.applicability.canonical_dict(),
        "verdict_schema": list(t.verdict_schema),
    }
    if t.clause_ref is not None:
        out["clause_ref"] = t.clause_ref
    if t.stored is not None:
        out["d_digest"] = t.stored.d_digest
        out["forward_verdict"] = t.stored.forward_verdict
        out["backward_verdict"] = t.stored.backward_verdict
        if t.stored.refusal_reason_code is not None:
            out["refusal_reason_code"] = t.stored.refusal_reason_code
    else:
        out["d_digest"] = json_digest(_declaration_canonical_dict(t.declaration))
    if t.judge_spec is not None:
        out["judge_spec"] = t.judge_spec.canonical_dict()
    if t.rule_kind is not None:
        out["rule_kind"] = t.rule_kind
    if t.tier != "informational":
        out["tier"] = t.tier
    if t.mode != "structural":
        out["mode"] = t.mode
    return out


@dataclass(frozen=True)
class TermsDocument:
    """``T`` (design §1): the confirmed terms document. ``t_digest`` is a
    pure content digest over the terms themselves -- ``t_prev_digest`` (the
    chain link to whatever ``T`` this one replaces) is carried as a sibling
    field on the sealed record, never inside this digest, mirroring
    ``compilation_record.py``'s own ``d_digest``/``d_prev_digest`` split."""

    terms: tuple[TermDeclaration, ...]

    def __post_init__(self) -> None:
        if not self.terms:
            raise CompilerError("a terms document must contain at least one term")
        ids = [t.term_id for t in self.terms]
        if len(ids) != len(set(ids)):
            dupes = sorted({i for i in ids if ids.count(i) > 1})
            raise CompilerError(f"duplicate term_id(s) in terms document: {dupes}")

    def canonical_dict(self) -> dict:
        ordered = sorted(self.terms, key=lambda t: t.term_id)
        return {"terms": [_term_to_canonical_dict(t) for t in ordered]}

    def digest(self) -> str:
        return json_digest(self.canonical_dict())


@dataclass(frozen=True)
class CompiledTerm:
    """One compiled row: ``A_i``/``F_i``/``J_i`` always; ``P_i`` only when
    ``compiled_declaration.forward.verdict == "DETERMINISTIC"`` (design
    §1); all four ``None`` except ``a_digest`` when the term is REFUSED."""

    term_id: str
    clause_ref: str | None
    applicability: ApplicabilitySpec
    a_digest: str
    compiled_declaration: CompiledDeclaration | None
    f_digest: str | None
    j_digest: str | None
    p_digest: str | None
    judge_or_rule: JudgeOrRuleSpec | None
    refusal_reason_code: str | None


def _compiled_declaration_for_term(term: TermDeclaration) -> CompiledDeclaration:
    """The one call site that actually reuses the real compiler -- never
    forked, never reimplemented (Amendment E)."""
    if term.stored is not None:
        return compiled_declaration_for(term.stored)
    assert term.declaration is not None
    return compile_declaration(term.declaration)


def compile_term(term: TermDeclaration) -> CompiledTerm:
    """One term -> ``A_i``/``F_i``/``J_i``(/``P_i``)."""
    a_digest = term.applicability.digest()
    compiled = _compiled_declaration_for_term(term)

    if compiled.backward.verdict == "REFUSED":
        return CompiledTerm(
            term_id=term.term_id,
            clause_ref=term.clause_ref,
            applicability=term.applicability,
            a_digest=a_digest,
            compiled_declaration=compiled,
            f_digest=None,
            j_digest=None,
            p_digest=None,
            judge_or_rule=None,
            refusal_reason_code=compiled.backward.refusal_reason_code,
        )

    f_digest = compiled.backward.digest()
    # A real forward guard config -- not merely a verdict string that
    # happens to read "DETERMINISTIC" -- requires an actual compiled plan.
    # Some pack-first candidate kinds (offer_response, decision) are graded
    # at propose time with no PlanDefinition ever compiled
    # (`compile_bridge.compiled_declaration_for`'s own docstring); emitting
    # a p_digest for those would claim a forward guard config that does not
    # exist.
    p_digest = (
        compiled.forward.digest()
        if compiled.forward.verdict == "DETERMINISTIC" and compiled.forward.plan is not None
        else None
    )

    if compiled.backward.verdict == "MODEL-ASSISTED":
        if term.judge_spec is None:
            raise CompilerError(f"term {term.term_id!r} compiled to MODEL-ASSISTED but carries no judge_spec")
        judge_or_rule = term.judge_spec
    else:
        if term.judge_spec is not None:
            raise CompilerError(
                f"term {term.term_id!r} compiled to backward verdict {compiled.backward.verdict!r}, not "
                "MODEL-ASSISTED -- judge_spec must be absent; the rule is derived from the compiled fold"
            )
        # DETERMINISTIC / WITH-INSTRUMENTATION / MANUAL: the "rule" is
        # exactly what the compiled fold already encodes -- pin its digest
        # rather than re-describing it.
        judge_or_rule = JudgeOrRuleSpec(
            kind="deterministic_rule",
            verdict_schema=term.verdict_schema,
            rule_digest=f_digest,
            rule_kind=term.rule_kind or "fact",
        )
    j_digest = judge_or_rule.digest()

    return CompiledTerm(
        term_id=term.term_id,
        clause_ref=term.clause_ref,
        applicability=term.applicability,
        a_digest=a_digest,
        compiled_declaration=compiled,
        f_digest=f_digest,
        j_digest=j_digest,
        p_digest=p_digest,
        judge_or_rule=judge_or_rule,
        refusal_reason_code=None,
    )


def compile_terms_document(doc: TermsDocument) -> tuple[CompiledTerm, ...]:
    return tuple(compile_term(t) for t in sorted(doc.terms, key=lambda t: t.term_id))


def compiled_term_digest(ct: CompiledTerm) -> str:
    """``c_digest`` -- "the term's own compiled-artifact digest, C's per-term
    digest" (epic chunk 3's ``judge_agent.payload.TermRef`` docstring, which
    names this value but could not produce it because this profile, epic
    chunk 2, had not been built yet). The digest of exactly the row this
    term seals into ``C`` (``_compiled_term_to_row``) -- never a second,
    hand-typed notion of "this term's version" that could drift from what
    actually got sealed. Changes exactly when the sealed row would change,
    including across a renegotiation that alters this term's
    ``a_digest``/``f_digest``/``j_digest``/``p_digest`` -- which is what
    makes report-time partitioning by ``c_digest`` (design §3 [rev]: "a
    range spanning T_v1->T_v2 renders the affected terms as two lines, one
    per compiled version") a correct proxy for "did this term's compiled
    definition change," including for a REFUSED term (whose row carries
    only ``term_id``/``a_digest``/``clause_ref``/``refusal_reason_code``,
    still a real, comparable version)."""
    return json_digest(_compiled_term_to_row(ct))


def _compiled_term_to_row(ct: CompiledTerm) -> dict:
    row: dict[str, Any] = {"term_id": ct.term_id, "a_digest": ct.a_digest}
    if ct.clause_ref is not None:
        row["clause_ref"] = ct.clause_ref
    if ct.f_digest is not None:
        row["f_digest"] = ct.f_digest
    if ct.j_digest is not None:
        row["j_digest"] = ct.j_digest
    if ct.p_digest is not None:
        row["p_digest"] = ct.p_digest
    if ct.refusal_reason_code is not None:
        row["refusal_reason_code"] = ct.refusal_reason_code
    return row


def build_terms_compilation_record_capsule(
    compiled_terms: tuple[CompiledTerm, ...],
    *,
    t_digest: str,
    operator: str,
    developer: str,
    signer: Signer,
    t_prev_digest: str | None = None,
    timestamp: str | None = None,
    action_id: str | None = None,
) -> dict:
    """Seal ``C`` for a terms document: ``{t_digest, terms: [...], compiler_id,
    compiler_version, [t_prev_digest]}``. ``t_prev_digest`` is omitted (not
    null) on a genesis terms document, same convention as
    ``compilation_record.build_compilation_record_capsule``'s
    ``d_prev_digest``."""
    if not is_hex64(t_digest):
        raise ValueError(f"t_digest must be a 64-hex SHA-256 digest; got {t_digest!r}")
    if t_prev_digest is not None and not is_hex64(t_prev_digest):
        raise ValueError(f"t_prev_digest must be a 64-hex SHA-256 digest or None; got {t_prev_digest!r}")
    if not compiled_terms:
        raise ValueError("compiled_terms must be non-empty")

    rows = sorted((_compiled_term_to_row(ct) for ct in compiled_terms), key=lambda r: r["term_id"])
    detail: dict[str, Any] = {
        "t_digest": t_digest,
        "terms": rows,
        "compiler_id": COMPILER_ID,
        "compiler_version": COMPILER_VERSION,
    }
    if t_prev_digest is not None:
        detail["t_prev_digest"] = t_prev_digest

    return build_event_capsule(
        operator=operator,
        developer=developer,
        signer=signer,
        event=EVENT_TERMS_COMPILATION_RECORD,
        detail=detail,
        timestamp=timestamp,
        action_id=action_id or f"compiler.terms_compilation_record/{t_digest}",
    )


@dataclass(frozen=True)
class TermDriftEntry:
    """Per-term drift, one entry per ``term_id`` seen either in the
    recompiled document or the sealed record (whichever has more rows)."""

    a_drifted: bool
    f_drifted: bool
    j_drifted: bool
    p_drifted: bool
    pf_incoherent: bool
    missing_in_sealed: bool
    extra_in_sealed: bool

    @property
    def drifted(self) -> bool:
        return (
            self.a_drifted
            or self.f_drifted
            or self.j_drifted
            or self.p_drifted
            or self.pf_incoherent
            or self.missing_in_sealed
            or self.extra_in_sealed
        )


@dataclass(frozen=True)
class TermsDriftResult:
    drifted: bool
    t_drifted: bool
    recomputed_t_digest: str
    sealed_t_digest: str
    per_term: dict[str, TermDriftEntry]


def _pf_incoherent(compiled: CompiledDeclaration) -> bool:
    """Digest equality proves co-derivation (both halves came from the
    same compile run), never correspondence (both halves mean the same
    thing) -- the lesson the compiler's own P/F non-correspondence bug
    demonstrated: a plan admitting one action class and a fold counting a
    disjoint one can still each recompute to their own recorded digest.
    Only meaningful when both a plan and a fold were actually compiled."""
    plan = compiled.forward.plan
    fold = compiled.backward.fold
    if plan is None or fold is None:
        return False
    fold_action_classes: set[str] = set()
    for clause in fold.filter:
        if clause.field == "asg_payload.action_class" and clause.op == "in":
            fold_action_classes = set(clause.value)
    if not fold_action_classes:
        # The fold places no action-class filter at all -- coherent only if
        # the plan likewise admits nothing (an unfiltered fold and a
        # nonempty admitted-action plan would silently disagree about scope).
        return len(plan.allowed_actions) > 0
    return fold_action_classes != set(plan.allowed_actions)


def verify_terms_compilation_record(sealed_detail: dict, *, t_document: TermsDocument) -> TermsDriftResult:
    """Recompute ``t_digest`` and every per-term digest from the confirmed
    ``TermsDocument`` itself -- never from the sealed record's own claims
    (hole 1: check against the sealed SOURCE, not only for internal
    drift). For every term whose forward verdict is DETERMINISTIC,
    independently re-confirms the recompiled plan and fold agree on scope
    (hole 2: co-derivation is not correspondence). A verifier who did not
    run the original compile can hold ``T`` alone, call this, and trust the
    result -- exactly ``compile.verify_compilation_record``'s property,
    extended to many terms and to the coherence check its own history
    shows digest-equality-alone misses."""
    recomputed_terms = compile_terms_document(t_document)
    recomputed_t_digest = t_document.digest()
    sealed_t_digest = sealed_detail["t_digest"]
    t_drifted = sealed_t_digest != recomputed_t_digest

    sealed_rows = {row["term_id"]: row for row in sealed_detail.get("terms", [])}
    recomputed_ids = {ct.term_id for ct in recomputed_terms}
    per_term: dict[str, TermDriftEntry] = {}

    for ct in recomputed_terms:
        row = sealed_rows.get(ct.term_id)
        missing = row is None
        a_drifted = missing or row.get("a_digest") != ct.a_digest
        f_drifted = missing or row.get("f_digest") != ct.f_digest
        j_drifted = missing or row.get("j_digest") != ct.j_digest
        sealed_p = None if missing else row.get("p_digest")
        p_drifted = (ct.p_digest is not None) != (sealed_p is not None) or (
            ct.p_digest is not None and ct.p_digest != sealed_p
        )
        incoherent = (
            _pf_incoherent(ct.compiled_declaration)
            if ct.p_digest is not None and ct.compiled_declaration is not None
            else False
        )
        per_term[ct.term_id] = TermDriftEntry(
            a_drifted=a_drifted,
            f_drifted=f_drifted,
            j_drifted=j_drifted,
            p_drifted=p_drifted,
            pf_incoherent=incoherent,
            missing_in_sealed=missing,
            extra_in_sealed=False,
        )

    for term_id in sorted(set(sealed_rows) - recomputed_ids):
        per_term[term_id] = TermDriftEntry(
            a_drifted=True,
            f_drifted=True,
            j_drifted=True,
            p_drifted=True,
            pf_incoherent=False,
            missing_in_sealed=False,
            extra_in_sealed=True,
        )

    drifted = t_drifted or any(entry.drifted for entry in per_term.values())
    return TermsDriftResult(
        drifted=drifted,
        t_drifted=t_drifted,
        recomputed_t_digest=recomputed_t_digest,
        sealed_t_digest=sealed_t_digest,
        per_term=per_term,
    )


def evaluate_term_fold(
    compiled_term: CompiledTerm,
    records: list[dict],
    *,
    range_start: int = 0,
    as_of: str | None = None,
    epoch: str | None = None,
) -> dict[Any, EvaluationTrace]:
    """``F_i`` evaluated with ``(range, as_of, epoch)`` as FORMAL PARAMETERS
    from T1 (design §3 [rev]): ``records``/``range_start`` are the
    committed range, ``as_of`` anchors any rolling window (reusing
    ``folds.engine.evaluate_all`` whole -- no new fold engine), and
    ``epoch`` scopes to one judge epoch's verdicts once the daily judge /
    epoch registry (a later stage of this epic) starts writing
    ``asg_payload.epoch`` onto satellite capsules. No producer writes that
    field yet, so passing ``epoch`` today is inert -- but it is a real
    parameter of this function from day one, so a later epoch never
    requires redefining ``F_i`` itself (the mid-history fold-digest-change
    failure the design names explicitly).

    Returns one ``EvaluationTrace`` per group key (design §2: "agent-scoped
    terms fold per-agent, fleet-level terms fold across all" -- the
    compiled fold's own ``key`` already decides which one a term is)."""
    if compiled_term.compiled_declaration is None:
        raise CompilerError(f"term {compiled_term.term_id!r} was REFUSED -- there is no fold to evaluate")
    fold = compiled_term.compiled_declaration.backward.fold
    if fold is None:
        raise CompilerError(
            f"term {compiled_term.term_id!r} compiled to backward verdict "
            f"{compiled_term.compiled_declaration.backward.verdict!r} with no replayable fold -- its "
            "verdict is graded at propose/judge time, not replayed from a FoldDefinition"
        )
    scoped = (
        records if epoch is None else [r for r in records if get_path(r, "asg_payload.epoch", None) == epoch]
    )
    return evaluate_all(fold, scoped, as_of=as_of, range_start=range_start)
