# SPDX-License-Identifier: Apache-2.0
"""English statement -> draft declaration ([ldg-english-to-declaration-drafter]):
the authoring path the product doc names as the one admitted gap -- until
now, ``capsule setup propose --drafter`` (``prose_drafter.py``, PR #67) only
drafted free-text RATIONALE for a candidate that had *already* matched real
ledger evidence; there was no seam that took an arbitrary English statement
and produced the candidate STRUCTURE itself.

BYOM, zero model calls unless a drafter is explicitly invoked
(``draft_declaration`` never imports a model client at module scope --
``DeepEvalDeclarationDrafter`` lazily imports ``deepeval``, same seam as
``prose_drafter.DeepEvalRationaleDrafter``). The result is a PROPOSAL: it is
persisted at ``acceptance_state="proposed"`` exactly like every other
candidate ``setup propose`` drafts, and requires the SAME human confirm at
T1 (``setup.confirm.confirm_accept``) -- or, for an unmappable statement,
acknowledgment of a REFUSED verdict at T4 (``confirm_acknowledge_refusal``).
Nothing here appends to the ledger or flips an acceptance state itself.

**The invariant (restates PR #67's own acceptance bar for declaration
drafting instead of rationale drafting):** the deterministic evaluation of a
drafted candidate -- its forward/backward verdict, coverage N-of-M, and
digest -- depends ONLY on the candidate's structural fields (kind + params)
and real ledger evidence, NEVER on which drafter (or none) produced that
structure. This module never computes a verdict or a coverage number itself
-- ``draft_declaration`` hands the drafted candidate straight to
``propose.propose_from_ledger``, the SAME deterministic machinery every
other candidate goes through, with ``allow_zero_coverage=True`` so a
freshly drafted declaration is never silently dropped just because no
traffic has hit it yet. Drafter provenance (``model_id``, ``prompt_digest``)
travels alongside the result but outside ``candidate_to_canonical_dict`` --
see ``propose.ProposedOutcome`` and ``declarations.StoredCandidate`` -- so a
candidate assembled by hand and the SAME candidate structure drafted by a
model from English text propose byte-identical verdict/coverage/digest;
only provenance and rationale prose may differ.

**Statement kind, closed:** a drafted candidate must be one of the same
three evidence-rule kinds ``candidates.py`` already knows (attainment,
offer_response, decision) -- there is no fourth kind this module invents.
A statement that fits none of them is not a bug in the drafter; it is
handled the same way ``compiler/effect_model.py`` handles an undecomposable
effect claim -- refusing IS the successful, expected return, never an
exception -- via ``RefusedCandidate(reason_code="statement_not_mappable")``
(``compiler/vocabulary.py``'s third, deliberately-extended reason code).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Protocol, runtime_checkable

from agent_action_capsule.canonical import json_digest

from ..ledger.api import LedgerAPI
from .candidates import (
    AttainmentCandidate,
    Candidate,
    DecisionCandidate,
    OfferResponseCandidate,
    RefusedCandidate,
)
from .propose import ProposedOutcome, propose_from_ledger
from .prose_drafter import DRAFTER_DEPENDENCY_MISSING, DrafterError

__all__ = [
    "DRAFTER_DEPENDENCY_MISSING",
    "DRAFTER_UNPARSEABLE_OUTPUT",
    "STATEMENT_NOT_MAPPABLE",
    "DrafterError",
    "DraftedDeclaration",
    "DeclarationDrafter",
    "StaticDeclarationDrafter",
    "DeepEvalDeclarationDrafter",
    "draft_declaration",
]

STATEMENT_NOT_MAPPABLE = "statement_not_mappable"
DRAFTER_UNPARSEABLE_OUTPUT = "drafter_unparseable_output"


def _prompt_digest(*, model_id: str, statement: str, outcome_id: str) -> str:
    """SHA-256 over the JCS bytes of exactly what was sent to the drafter --
    same idiom as ``judge/prompt.py``'s ``prompt_digest()``, sized to this
    seam rather than standing up a full prompt-definition registry for a
    single call site."""
    return json_digest({"drafter_model_id": model_id, "statement": statement, "outcome_id": outcome_id})


@dataclass(frozen=True)
class DraftedDeclaration:
    """A drafter's output: always a real ``Candidate`` -- a
    ``RefusedCandidate(reason_code="statement_not_mappable")`` when the
    statement could not be mapped, never ``None`` and never an exception,
    so callers have exactly one shape to handle (design's own "refusing IS
    the successful return" doctrine, restated for authoring time)."""

    candidate: Candidate
    model_id: str
    prompt_digest: str


@runtime_checkable
class DeclarationDrafter(Protocol):
    def draft(self, statement: str, *, outcome_id: str) -> DraftedDeclaration: ...


# Static reference drafter's inline-hint grammar: `kind:<attainment|
# offer_response|decision>` plus `action_class:<id>` or `offer_namespace:
# <id>`, matching the open, registry-resolved naming convention
# `candidates.py`'s own DEFAULT_CANDIDATES uses (e.g. "remediation",
# "advisory"). This is a wiring-proof stand-in, not real language
# understanding -- same role as `StaticRationaleDrafter`/judge's
# `StaticScorer`: a real deployment drafts declarations with
# `DeepEvalDeclarationDrafter`, which reads free text with a model instead.
#
# ``[remove-keyword-scorers]`` (2026-08-29) removed this drafter's PRIOR
# classification path: it used to guess `kind` from whether a fixed list of
# ordinary English words ("authorized", "offer", "confirmed") appeared
# anywhere in the statement -- a keyword scorer masquerading as a
# structural parser, exactly the anti-pattern this task targets. `kind` is
# now itself an explicit hint, same shape and same regex as
# `action_class`/`offer_namespace` -- this drafter no longer infers
# anything from ordinary prose, it only reads annotations a human
# deliberately embedded (the same closed vocabulary
# `DeepEvalDeclarationDrafter`'s own prompt already asks a live model to
# emit via its `kind=...` output line).
_PARAM_RE = re.compile(r"\b(action_class|offer_namespace|kind):([a-z][a-z0-9_.]*)\b")


def _strip_hints(statement: str) -> str:
    """The persisted ``Outcome.statement`` is a disclosable field an auditor
    reads (design §3.6) -- it must never carry this reference drafter's own
    inline ``kind:``/``action_class:``/``offer_namespace:`` extraction
    syntax. Strips each hint token and any now-empty enclosing parens (now
    possibly carrying nothing but whitespace and the ``; `` separator
    between two or more stripped hints, e.g. ``(kind:x; action_class:y)`` ->
    ``(; )``), leaving the plain English sentence a human actually wrote."""
    cleaned = _PARAM_RE.sub("", statement)
    cleaned = re.sub(r"\([\s;]*\)", "", cleaned)
    return re.sub(r"\s{2,}", " ", cleaned).strip()


@dataclass(frozen=True)
class StaticDeclarationDrafter:
    """No-network deterministic reference (``--drafter static``): proves the
    ``draft_declaration`` plumbing end to end without a model call or
    nondeterminism. Classifies by a fixed, tiny STRUCTURED hint grammar --
    an explicit ``kind:<attainment|offer_response|decision>`` annotation
    plus ``action_class:``/``offer_namespace:``, never a guess from ordinary
    prose (see the module comment above ``_PARAM_RE``). Statements that
    don't carry an explicit ``kind:`` hint, or whose ``kind:`` names
    something other than the three known evidence-rule kinds, or that are
    missing the param hint their kind requires, are honestly reported as
    unmappable rather than guessed at."""

    model_id: str = "static-drafter/deterministic"

    def draft(self, statement: str, *, outcome_id: str) -> DraftedDeclaration:
        prompt_digest = _prompt_digest(model_id=self.model_id, statement=statement, outcome_id=outcome_id)
        lowered = statement.lower()
        params = dict(_PARAM_RE.findall(lowered))
        kind = params.get("kind")
        clean_statement = _strip_hints(statement)

        candidate: Candidate
        if kind == "decision" and "action_class" in params:
            candidate = DecisionCandidate(outcome_id=outcome_id, statement=clean_statement, action_class=params["action_class"])
        elif kind == "offer_response":
            candidate = OfferResponseCandidate(
                outcome_id=outcome_id, statement=clean_statement, offer_namespace=params.get("offer_namespace", "advisory")
            )
        elif kind == "attainment" and "action_class" in params:
            candidate = AttainmentCandidate(outcome_id=outcome_id, statement=clean_statement, action_class=params["action_class"])
        else:
            candidate = RefusedCandidate(outcome_id=outcome_id, statement=clean_statement, reason_code=STATEMENT_NOT_MAPPABLE)

        return DraftedDeclaration(candidate=candidate, model_id=self.model_id, prompt_digest=prompt_digest)


_CLASSIFICATION_RE = re.compile(
    r"kind=(attainment|offer_response|decision|unmappable)"
    r"(?:;\s*action_class=([a-z][a-z0-9_.]*))?"
    r"(?:;\s*offer_namespace=([a-z][a-z0-9_.]*))?"
)


class DeepEvalDeclarationDrafter:
    """The default BYOM drafter (``--drafter deepeval``): one ``deepeval``
    G-Eval call per statement, prompted to classify it into the closed
    candidate-kind vocabulary and emit ONE parseable line -- the same
    "prompted contract read back out of ``.reason``" idiom
    ``DeepEvalRationaleDrafter`` uses for prose, applied here to a strict
    machine-parseable format instead of free paragraphs. ``deepeval`` is an
    optional dependency, imported lazily so ``capsule_ledger.setup`` stays
    importable without it."""

    def __init__(self, *, model: str | None = None):
        try:
            from deepeval.metrics import GEval
            from deepeval.test_case import LLMTestCase, SingleTurnParams
        except ImportError as exc:
            raise DrafterError(
                DRAFTER_DEPENDENCY_MISSING,
                "DeepEvalDeclarationDrafter requires the optional 'deepeval' package -- "
                "install with `pip install capsule-ledger[judge]`",
            ) from exc
        self._GEval = GEval
        self._LLMTestCase = LLMTestCase
        self._eval_params = [SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT]
        self._model = model
        self.model_id = model or "deepeval/g-eval-default"

    def draft(self, statement: str, *, outcome_id: str) -> DraftedDeclaration:
        prompt_digest = _prompt_digest(model_id=self.model_id, statement=statement, outcome_id=outcome_id)
        test_case = self._LLMTestCase(input=statement, actual_output=statement)
        metric = self._GEval(
            name=f"declaration-drafter::{outcome_id}",
            criteria=(
                "Classify the given English statement into exactly ONE of three evidence-rule "
                "kinds: 'attainment' (an action of some class was confirmed by an external system), "
                "'offer_response' (a person was offered a choice and their response is on record), "
                "'decision' (an action of some class was authorized by policy rather than blocked). "
                "If none fits, use 'unmappable'. Reply with EXACTLY one line of the form "
                "'kind=<attainment|offer_response|decision|unmappable>; action_class=<id>' (attainment/decision) "
                "or 'kind=offer_response; offer_namespace=<id>' (offer_response) or 'kind=unmappable' -- "
                "no other text, no explanation."
            ),
            evaluation_params=self._eval_params,
            model=self._model,
        )
        metric.measure(test_case)
        drafted = getattr(metric, "reason", None) or ""
        match = _CLASSIFICATION_RE.search(drafted)
        if match is None:
            raise DrafterError(
                DRAFTER_UNPARSEABLE_OUTPUT,
                f"DeepEvalDeclarationDrafter produced no parseable classification for {outcome_id!r}: {drafted!r}",
            )
        kind, action_class, offer_namespace = match.groups()

        candidate: Candidate
        if kind == "decision" and action_class:
            candidate = DecisionCandidate(outcome_id=outcome_id, statement=statement, action_class=action_class)
        elif kind == "offer_response":
            candidate = OfferResponseCandidate(
                outcome_id=outcome_id, statement=statement, offer_namespace=offer_namespace or "advisory"
            )
        elif kind == "attainment" and action_class:
            candidate = AttainmentCandidate(outcome_id=outcome_id, statement=statement, action_class=action_class)
        else:
            candidate = RefusedCandidate(outcome_id=outcome_id, statement=statement, reason_code=STATEMENT_NOT_MAPPABLE)

        return DraftedDeclaration(candidate=candidate, model_id=self.model_id, prompt_digest=prompt_digest)


def draft_declaration(
    statement: str, *, outcome_id: str, drafter: DeclarationDrafter, ledger: LedgerAPI
) -> ProposedOutcome:
    """Draft ONE candidate from ``statement`` via ``drafter``, then evaluate
    it through the SAME deterministic ``propose_from_ledger`` every other
    candidate goes through (``allow_zero_coverage=True`` -- see that
    function's own docstring). Returns exactly one ``ProposedOutcome``,
    carrying the drafter's provenance; never ``None`` -- a refused candidate
    still proposes (as REFUSED/REFUSED), and a zero-evidence candidate still
    proposes (as 0 of 0), so this never silently produces nothing."""
    drafted = drafter.draft(statement, outcome_id=outcome_id)
    proposal_set = propose_from_ledger(ledger, candidates=(drafted.candidate,), allow_zero_coverage=True)
    outcome = proposal_set.proposals[0]
    return replace(outcome, drafted_by_model_id=drafted.model_id, drafted_by_prompt_digest=drafted.prompt_digest)
