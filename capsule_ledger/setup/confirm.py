# SPDX-License-Identifier: Apache-2.0
"""``capsule setup confirm`` (design §3.2/§4/§6b): the two touchpoints a
machine cannot make for itself, plus the one that makes a refusal visible
instead of merely present. Every one of these produces a **recorded act,
never a config edit** -- nothing here rewrites a file in place; each call
appends a new, signed capsule to the ledger.

- **T1 -- declaration acceptance.** *"These are the outcomes we are
  claiming, and these are the rules for proving them."* Freezes the
  declaration+mapping pair as a sealed compilation record C
  (``compiler.compile.seal_compilation_record``), citing exactly the
  verdict pair ``propose`` computed (``compile_bridge.compiled_declaration_for``)
  -- never a live recompute against whatever the ledger looks like right
  now. Refuses to accept a candidate whose own verdict pair is REFUSED;
  that path is T4, not T1.
- **T2 -- scope census sign-off.** *"This pack covers N of the M outcomes
  in document D."* Independent of any one outcome_id -- it is a claim
  about the whole document, so it takes its own document digest/N/M
  directly (``compiler.scope_census.build_scope_census_capsule``).
- **T4 -- refusal acknowledgment.** A human must see and accept a REFUSED
  verdict before the refusal is real -- design §4: "without this the
  refusal is invisible and the operator concludes the feature is missing
  rather than that the claim was unprovable." Seals the refusal capsule
  itself (design §2.2's compiler-refusal vocabulary) AND a second capsule
  recording the human's acknowledgment, chained to it.
- **T3 -- judge-prompt confirmation** ([outcomes-to-judgeprompt-compiler-t3]
  build spec point 2). The judge prompt a machine compiles
  (``judge.prompt_compiler.compile_judge_prompt``) is load-bearing: it is
  what a model actually reads to produce a judgment, so a human owns and
  signs the FINAL wording the same way T1 owns the outcome's acceptance.
  Mirrors T1/T4's recorded-act shape exactly -- ``decision="confirm"``
  seals the compiled candidate verbatim; ``decision="review_edit"`` seals
  an EDITED prompt instead, which naturally reseals under a different
  ``prompt_digest`` (the digest commits to ``instructions``, so a wording
  change is never silently absorbed). Chains to the compilation record C
  the caller names (T1's ``confirm_accept`` return, or a terms-desk C) with
  relation ``confirms`` -- the prompt observes/records against an already-
  sealed C, it never supersedes it.
"""
from __future__ import annotations

from dataclasses import replace

from ..compiler.compilation_record import EVENT_COMPILATION_RECORD
from ..compiler.compile import seal_compilation_record
from ..compiler.refusal import EVENT_REFUSAL, build_refusal_capsule
from ..compiler.scope_census import build_scope_census_capsule
from ..guards.capsule import build_event_capsule
from ..guards.signing import Signer
from ..judge.prompt import JudgePromptDefinition
from ..ledger.api import LedgerAPI
from .compile_bridge import compiled_declaration_for
from .declarations import DeclarationStore

__all__ = [
    "EVENT_COMPILATION_RECORD",
    "EVENT_JUDGE_PROMPT_CONFIRMED",
    "EVENT_REFUSAL",
    "EVENT_REFUSAL_ACKNOWLEDGED",
    "PROMPT_CONFIRM_DECISIONS",
    "ConfirmError",
    "confirm_accept",
    "confirm_acknowledge_refusal",
    "confirm_prompt",
    "confirm_scope_census",
]

EVENT_REFUSAL_ACKNOWLEDGED = "compiler.refusal_acknowledged"
EVENT_JUDGE_PROMPT_CONFIRMED = "compiler.judge_prompt_confirmed"

# The CLI's own vocabulary for the T3 touchpoint -- "(C)onfirm / (R)eview-edit"
# (build spec point 2). Closed set, same "unregistered is a typo" doctrine
# every other closed vocabulary in this codebase follows.
PROMPT_CONFIRM_DECISIONS = frozenset({"confirm", "review_edit"})


class ConfirmError(ValueError):
    """A confirm verb was asked to do something its own touchpoint does not
    cover -- e.g. T1-accepting a REFUSED candidate (that is T4's job), or
    T4-acknowledging a candidate that was never refused."""


def confirm_accept(
    outcome_id: str,
    *,
    store: DeclarationStore,
    ledger: LedgerAPI,
    signer: Signer,
    operator: str,
    developer: str,
    d_prev_digest: str | None = None,
    replay_report_digest: str | None = None,
) -> dict:
    """T1. Seals C for ``outcome_id`` and flips its stored acceptance state
    to ``accepted``. Idempotent in effect but not in the ledger: calling
    this twice appends two compilation-record capsules (a re-acceptance is
    itself a recordable act, not an error) -- callers that only want a
    fresh acceptance when something changed should check
    ``store.load(outcome_id).acceptance_state`` first."""
    stored = store.load(outcome_id)
    if stored.forward_verdict == "REFUSED" or stored.backward_verdict == "REFUSED":
        raise ConfirmError(
            f"{outcome_id!r} is REFUSED (forward={stored.forward_verdict}, backward={stored.backward_verdict}) "
            "-- accept a refusal with confirm_acknowledge_refusal (T4), not confirm_accept (T1)"
        )
    compiled = compiled_declaration_for(stored)
    record = seal_compilation_record(
        compiled,
        d_digest=stored.d_digest,
        operator=operator,
        developer=developer,
        signer=signer,
        d_prev_digest=d_prev_digest,
        replay_report_digest=replay_report_digest,
    )
    ledger.append(record, consequential=False)
    store.set_acceptance_state(outcome_id, "accepted")
    return record


def confirm_scope_census(
    *,
    document_digest: str,
    n: int,
    m: int,
    review_by: str,
    ledger: LedgerAPI,
    signer: Signer,
    operator: str,
    developer: str,
    chain_parent: str | None = None,
) -> dict:
    """T2. Not scoped to one outcome_id -- a census asserts what the WHOLE
    document's universe is, which is exactly the auditor's first question
    and, for obligations, the entire regulatory one (design §4)."""
    capsule = build_scope_census_capsule(
        document_digest=document_digest,
        n=n,
        m=m,
        review_by=review_by,
        operator=operator,
        developer=developer,
        signer=signer,
        chain_parent=chain_parent,
    )
    ledger.append(capsule, consequential=False)
    return capsule


def confirm_acknowledge_refusal(
    outcome_id: str,
    *,
    store: DeclarationStore,
    ledger: LedgerAPI,
    signer: Signer,
    operator: str,
    developer: str,
    acknowledged_by: str,
) -> tuple[dict, dict]:
    """T4. Requires ``outcome_id`` to actually be REFUSED (a T1-eligible
    candidate has nothing here to acknowledge). Returns
    ``(refusal_capsule, acknowledgment_capsule)`` -- the refusal itself,
    chained ``confirms`` by the human's acknowledgment, so the ledger
    carries both "the compiler refused this" and "a named human saw and
    accepted that refusal" as two separately-checkable facts."""
    stored = store.load(outcome_id)
    compiled = compiled_declaration_for(stored)
    verdict = compiled.verdict_pair
    if "REFUSED" not in (verdict.forward, verdict.backward):
        raise ConfirmError(
            f"{outcome_id!r} is not REFUSED (forward={verdict.forward}, backward={verdict.backward}) "
            "-- nothing for T4 to acknowledge"
        )
    reason_code = stored.refusal_reason_code
    if reason_code is None:
        raise ConfirmError(f"{outcome_id!r} is REFUSED but has no stored refusal_reason_code -- cannot seal a refusal capsule")

    refusal_capsule = build_refusal_capsule(
        verdict=verdict,
        statement_digest=stored.d_digest,
        reason_code=reason_code,
        operator=operator,
        developer=developer,
        signer=signer,
    )
    ledger.append(refusal_capsule, consequential=False)

    ack_capsule = build_event_capsule(
        operator=operator,
        developer=developer,
        signer=signer,
        event=EVENT_REFUSAL_ACKNOWLEDGED,
        detail={"outcome_id": outcome_id, "acknowledged_by": acknowledged_by},
        chain_parent=refusal_capsule["capsule_id"],
        chain_relation="confirms",
    )
    ledger.append(ack_capsule, consequential=False)

    store.set_acceptance_state(outcome_id, "refused")
    return refusal_capsule, ack_capsule


def confirm_prompt(
    outcome_id: str,
    *,
    generated_prompt: JudgePromptDefinition,
    decision: str,
    compilation_record_capsule_id: str,
    ledger: LedgerAPI,
    signer: Signer,
    operator: str,
    developer: str,
    store: DeclarationStore | None = None,
    edited_instructions: str | None = None,
) -> dict:
    """T3. Seals the FINAL judge prompt for ``outcome_id`` -- either
    ``generated_prompt`` verbatim (``decision="confirm"``) or an edited copy
    of it (``decision="review_edit"``, ``edited_instructions`` required) --
    as a signed capsule chained to ``compilation_record_capsule_id`` with
    relation ``"confirms"``.

    ``store``, when given, gates this the same way ``compiled_declaration_for``
    gates T1/T4: ``outcome_id`` must already be T1-accepted
    (``acceptance_state == "accepted"``) -- design's 6-step flow confirms the
    OUTCOME (T1) before it confirms the outcome's JUDGE PROMPT (T3), never
    the other way around. Omit ``store`` only for a caller that has already
    verified acceptance some other way (e.g. the terms-desk profile, which
    tracks acceptance across a whole ``TermsDocument`` rather than per-call).

    Editing changes ``instructions`` only -- ``prompt_id``/``label_set``/
    ``model_id_hint`` carry over from ``generated_prompt`` unchanged, so a
    reviewer's edit is a wording correction, never a silent re-scoping of
    what the prompt is even for. Because ``prompt_digest()`` commits to
    ``instructions``, an edited prompt seals under a DIFFERENT digest than
    the machine-compiled candidate -- the sealed capsule is always the
    prompt that will actually run, never the one a human merely glanced at.
    """
    if decision not in PROMPT_CONFIRM_DECISIONS:
        raise ConfirmError(f"decision must be one of {sorted(PROMPT_CONFIRM_DECISIONS)}; got {decision!r}")
    if decision == "review_edit":
        if not edited_instructions or not edited_instructions.strip():
            raise ConfirmError("decision='review_edit' requires non-empty edited_instructions")
        final_prompt = replace(generated_prompt, instructions=edited_instructions)
    else:
        if edited_instructions is not None:
            raise ConfirmError("edited_instructions is only used with decision='review_edit'")
        final_prompt = generated_prompt

    if store is not None:
        stored = store.load(outcome_id)
        if stored.acceptance_state != "accepted":
            raise ConfirmError(
                f"{outcome_id!r} is not yet accepted (T1) -- acceptance_state={stored.acceptance_state!r}; "
                "confirm the outcome (confirm_accept) before confirming its judge prompt (T3)"
            )

    prompt_digest = final_prompt.prompt_digest()
    detail: dict = {
        "outcome_id": outcome_id,
        "prompt_id": final_prompt.prompt_id,
        "prompt_digest": prompt_digest,
        "label_set": list(final_prompt.label_set),
        "instructions": final_prompt.instructions,
        "edited": decision == "review_edit",
    }
    if final_prompt.model_id_hint is not None:
        detail["model_id_hint"] = final_prompt.model_id_hint

    capsule = build_event_capsule(
        operator=operator,
        developer=developer,
        signer=signer,
        event=EVENT_JUDGE_PROMPT_CONFIRMED,
        detail=detail,
        chain_parent=compilation_record_capsule_id,
        chain_relation="confirms",
    )
    ledger.append(capsule, consequential=False)
    return capsule
