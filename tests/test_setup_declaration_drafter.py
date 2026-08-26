# SPDX-License-Identifier: Apache-2.0
import io
import re

import pytest

from capsule_ledger.compiler.vocabulary import REFUSAL_REASON_CODES
from capsule_ledger.setup.candidates import (
    AttainmentCandidate,
    DecisionCandidate,
    OfferResponseCandidate,
    RefusedCandidate,
)
from capsule_ledger.setup.compile_bridge import compiled_declaration_for
from capsule_ledger.setup.confirm import confirm_accept, confirm_acknowledge_refusal
from capsule_ledger.setup.declaration_drafter import (
    STATEMENT_NOT_MAPPABLE,
    StaticDeclarationDrafter,
    draft_declaration,
)
from capsule_ledger.setup.declarations import DeclarationStore, StoredCandidate, candidate_digest
from capsule_ledger.setup.observe import ObserveRecorder
from capsule_ledger.setup.propose import propose_from_ledger

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _observe(store, signer, events):
    recorder = ObserveRecorder(
        ledger=store, signer=signer, operator="op", developer="dev", heartbeat_every=0, heartbeat_stream=io.StringIO()
    )
    return recorder.run(events)


# --- STATEMENT_NOT_MAPPABLE is a real, closed vocabulary member -----------


def test_statement_not_mappable_is_registered_in_the_closed_vocabulary():
    assert STATEMENT_NOT_MAPPABLE in REFUSAL_REASON_CODES


# --- StaticDeclarationDrafter classification -------------------------------


def test_static_drafter_maps_hinted_statement_to_attainment_candidate():
    drafter = StaticDeclarationDrafter()
    drafted = drafter.draft(
        "a remediation action was confirmed by an external system (action_class:remediation)",
        outcome_id="outcome.custom_remediation",
    )
    assert isinstance(drafted.candidate, AttainmentCandidate)
    assert drafted.candidate.action_class == "remediation"
    assert drafted.candidate.outcome_id == "outcome.custom_remediation"
    # the hint syntax never survives into the disclosable statement text
    assert "action_class:" not in drafted.candidate.statement
    assert drafted.model_id == "static-drafter/deterministic"
    assert _HEX64.match(drafted.prompt_digest)


def test_static_drafter_maps_offer_hint_to_offer_response_candidate():
    drafter = StaticDeclarationDrafter()
    drafted = drafter.draft(
        "a person was offered a choice and their response is on record (offer_namespace:advisory)",
        outcome_id="outcome.custom_choice",
    )
    assert isinstance(drafted.candidate, OfferResponseCandidate)
    assert drafted.candidate.offer_namespace == "advisory"


def test_static_drafter_offer_hint_defaults_namespace_when_omitted():
    drafter = StaticDeclarationDrafter()
    drafted = drafter.draft("a person was offered a choice", outcome_id="outcome.custom_choice")
    assert isinstance(drafted.candidate, OfferResponseCandidate)
    assert drafted.candidate.offer_namespace == "advisory"


def test_static_drafter_maps_hinted_statement_to_decision_candidate():
    drafter = StaticDeclarationDrafter()
    drafted = drafter.draft(
        "a change request was authorized by policy rather than blocked (action_class:booking.modify)",
        outcome_id="outcome.custom_change",
    )
    assert isinstance(drafted.candidate, DecisionCandidate)
    assert drafted.candidate.action_class == "booking.modify"


def test_static_drafter_refuses_a_statement_with_no_matching_kind():
    drafter = StaticDeclarationDrafter()
    drafted = drafter.draft("the interaction increased the counterparty's trust in the system", outcome_id="outcome.x")
    assert isinstance(drafted.candidate, RefusedCandidate)
    assert drafted.candidate.reason_code == STATEMENT_NOT_MAPPABLE


def test_static_drafter_refuses_when_kind_matched_but_no_param_hint():
    """RED-before-green for the drop-not-guess discipline: 'confirmed' alone
    triggers the attainment kind-word, but with no action_class hint there
    is nothing to grade evidence against, so this must refuse -- not invent
    a placeholder action_class."""
    drafter = StaticDeclarationDrafter()
    drafted = drafter.draft("a remediation action was confirmed by an external system", outcome_id="outcome.x")
    assert isinstance(drafted.candidate, RefusedCandidate)
    assert drafted.candidate.reason_code == STATEMENT_NOT_MAPPABLE


# --- draft_declaration: never silently drops a fresh candidate -------------


def test_draft_declaration_zero_evidence_reports_0_of_0_not_dropped(store, signer):
    drafter = StaticDeclarationDrafter()
    outcome = draft_declaration(
        "a remediation action was confirmed by an external system (action_class:remediation)",
        outcome_id="outcome.fresh_remediation",
        drafter=drafter,
        ledger=store,
    )
    assert outcome.coverage_n == 0
    assert outcome.coverage_m == 0
    assert outcome.forward_verdict == "DETERMINISTIC"
    assert outcome.backward_verdict == "DETERMINISTIC"
    assert outcome.drafted_by_model_id == "static-drafter/deterministic"
    assert _HEX64.match(outcome.drafted_by_prompt_digest)


def test_draft_declaration_grades_real_evidence(store, signer):
    events = []
    for i in range(1, 6):
        events.append({"kind": "dispatch", "dispatch_id": f"d{i}", "action_class": "remediation", "tool": "remediate"})
    for i in (1, 2, 3):
        events.append({"kind": "confirmation", "commitment_ref": f"d{i}", "status": "confirmed"})
    _observe(store, signer, events)

    drafter = StaticDeclarationDrafter()
    outcome = draft_declaration(
        "a remediation action was confirmed by an external system (action_class:remediation)",
        outcome_id="outcome.fresh_remediation",
        drafter=drafter,
        ledger=store,
    )
    assert outcome.coverage_n == 3
    assert outcome.coverage_m == 5


def test_default_batch_propose_still_drops_zero_evidence_candidates(store, signer):
    """Regression guard: propose_from_ledger's default (allow_zero_coverage
    unset) must stay byte-for-byte the old 'absent, not failing' behavior --
    the new declaration-drafting flow opts in explicitly, everyone else is
    untouched."""
    proposal_set = propose_from_ledger(
        store, candidates=(AttainmentCandidate(outcome_id="outcome.never_observed", statement="x", action_class="remediation"),)
    )
    assert proposal_set.proposals == ()


def test_unmappable_statement_still_proposes_as_refused_not_dropped(store, signer):
    drafter = StaticDeclarationDrafter()
    outcome = draft_declaration(
        "the interaction increased the counterparty's trust in the system", outcome_id="outcome.unmappable", drafter=drafter, ledger=store
    )
    assert outcome.is_refused
    assert outcome.refusal_reason_code == STATEMENT_NOT_MAPPABLE
    assert outcome.coverage_n is None
    assert outcome.coverage_m is None


# --- the invariant: model-on vs model-off byte-identical -------------------


def test_drafted_and_hand_authored_candidates_produce_byte_identical_d_digest(store, signer):
    """The core acceptance invariant (mirrors PR #67, restated for full
    declaration drafting): a candidate assembled by hand ('model off') and
    the SAME candidate structure drafted by a model from English text
    ('model on') must propose byte-identical verdict/coverage/digest --
    only drafter provenance may differ."""
    events = []
    for i in range(1, 4):
        events.append({"kind": "dispatch", "dispatch_id": f"d{i}", "action_class": "remediation", "tool": "remediate"})
    events.append({"kind": "confirmation", "commitment_ref": "d1", "status": "confirmed"})
    _observe(store, signer, events)

    outcome_id = "outcome.remediation_v2"
    hand_candidate = AttainmentCandidate(
        outcome_id=outcome_id, statement="a remediation action was confirmed by an external system", action_class="remediation"
    )
    drafted = StaticDeclarationDrafter().draft(
        "a remediation action was confirmed by an external system (action_class:remediation)", outcome_id=outcome_id
    )

    # model off: candidate hand-authored directly, never touching a drafter
    off_set = propose_from_ledger(store, candidates=(hand_candidate,), allow_zero_coverage=True)
    off = off_set.proposals[0]

    # model on: the SAME candidate structure, drafted from English text
    on = draft_declaration(
        "a remediation action was confirmed by an external system (action_class:remediation)",
        outcome_id=outcome_id,
        drafter=StaticDeclarationDrafter(),
        ledger=store,
    )

    assert drafted.candidate == hand_candidate
    assert candidate_digest(drafted.candidate) == candidate_digest(hand_candidate)
    assert on.forward_verdict == off.forward_verdict
    assert on.backward_verdict == off.backward_verdict
    assert on.coverage_n == off.coverage_n
    assert on.coverage_m == off.coverage_m
    assert on.statement == off.statement
    # provenance is the ONLY thing that differs
    assert off.drafted_by_model_id is None
    assert off.drafted_by_prompt_digest is None
    assert on.drafted_by_model_id == "static-drafter/deterministic"
    assert on.drafted_by_prompt_digest is not None

    # and the compiled digests (P/F) agree too, since compile_bridge is a
    # pure function of the candidate's own fields
    on_compiled = compiled_declaration_for(
        StoredCandidate(
            candidate=hand_candidate,
            acceptance_state="proposed",
            d_digest=candidate_digest(drafted.candidate),
            forward_verdict=on.forward_verdict,
            backward_verdict=on.backward_verdict,
        )
    )
    off_compiled = compiled_declaration_for(
        StoredCandidate(
            candidate=hand_candidate,
            acceptance_state="proposed",
            d_digest=candidate_digest(hand_candidate),
            forward_verdict=off.forward_verdict,
            backward_verdict=off.backward_verdict,
        )
    )
    assert on_compiled.forward.digest() == off_compiled.forward.digest()
    assert on_compiled.backward.digest() == off_compiled.backward.digest()


# --- worked example: English -> proposal -> confirm -> compile -------------


def test_worked_example_english_to_proposal_to_confirm_to_compile(store, signer, tmp_path):
    events = [
        {"kind": "dispatch", "dispatch_id": "d1", "action_class": "remediation", "tool": "remediate"},
        {"kind": "confirmation", "commitment_ref": "d1", "status": "confirmed"},
    ]
    _observe(store, signer, events)

    decl_store = DeclarationStore(tmp_path / "on")
    outcome_id = "outcome.worked_example"
    outcome = draft_declaration(
        "a remediation action was confirmed by an external system (action_class:remediation)",
        outcome_id=outcome_id,
        drafter=StaticDeclarationDrafter(),
        ledger=store,
    )
    decl_store.save(
        outcome.candidate,
        acceptance_state="proposed",
        forward_verdict=outcome.forward_verdict,
        backward_verdict=outcome.backward_verdict,
        drafted_by_model_id=outcome.drafted_by_model_id,
        drafted_by_prompt_digest=outcome.drafted_by_prompt_digest,
    )
    assert decl_store.load(outcome_id).acceptance_state == "proposed"
    assert decl_store.load(outcome_id).drafted_by_model_id == "static-drafter/deterministic"

    on_record = confirm_accept(outcome_id, store=decl_store, ledger=store, signer=signer, operator="op", developer="dev")
    assert decl_store.load(outcome_id).acceptance_state == "accepted"

    # model off: the operator hand-types the identical declaration under
    # the SAME outcome_id, never invoking a drafter at all -- a separate
    # store (and its own capsule chain) so the two runs don't collide.
    off_store = DeclarationStore(tmp_path / "off")
    hand_candidate = AttainmentCandidate(
        outcome_id=outcome_id, statement="a remediation action was confirmed by an external system", action_class="remediation"
    )
    hand_set = propose_from_ledger(store, candidates=(hand_candidate,))
    hand_proposed = hand_set.proposals[0]
    off_store.save(
        hand_candidate,
        acceptance_state="proposed",
        forward_verdict=hand_proposed.forward_verdict,
        backward_verdict=hand_proposed.backward_verdict,
    )
    off_record = confirm_accept(outcome_id, store=off_store, ledger=store, signer=signer, operator="op", developer="dev")

    on_detail = on_record["asg_payload"]["detail"]
    off_detail = off_record["asg_payload"]["detail"]
    assert on_detail["d_digest"] == off_detail["d_digest"]
    assert on_detail["p_digest"] == off_detail["p_digest"]
    assert on_detail["f_digest"] == off_detail["f_digest"]


def test_worked_example_unmappable_statement_through_refusal_path(store, signer, tmp_path):
    decl_store = DeclarationStore(tmp_path)
    outcome_id = "outcome.worked_example_refused"
    outcome = draft_declaration(
        "the interaction increased the counterparty's trust in the system",
        outcome_id=outcome_id,
        drafter=StaticDeclarationDrafter(),
        ledger=store,
    )
    assert outcome.is_refused
    decl_store.save(
        outcome.candidate,
        acceptance_state="proposed",
        forward_verdict=outcome.forward_verdict,
        backward_verdict=outcome.backward_verdict,
        refusal_reason_code=outcome.refusal_reason_code,
        drafted_by_model_id=outcome.drafted_by_model_id,
        drafted_by_prompt_digest=outcome.drafted_by_prompt_digest,
    )

    refusal_capsule, ack_capsule = confirm_acknowledge_refusal(
        outcome_id, store=decl_store, ledger=store, signer=signer, operator="op", developer="dev", acknowledged_by="alice"
    )
    detail = refusal_capsule["asg_payload"]["detail"]
    assert detail["reason_code"] == STATEMENT_NOT_MAPPABLE
    # zero free prose on the capsule -- fixed shape only
    assert set(detail.keys()) <= {"verdict_class", "statement_digest", "reason_code", "labelled_item"}
    assert ack_capsule["asg_payload"]["detail"]["outcome_id"] == outcome_id
    assert decl_store.load(outcome_id).acceptance_state == "refused"


def test_confirm_accept_still_rejects_a_drafted_refused_candidate(store, signer, tmp_path):
    """T1 stays T1: a REFUSED drafted candidate must go through T4, exactly
    the same rule as any other refused candidate (setup/confirm.py)."""
    decl_store = DeclarationStore(tmp_path)
    outcome_id = "outcome.worked_example_refused_2"
    outcome = draft_declaration(
        "the interaction increased the counterparty's trust in the system",
        outcome_id=outcome_id,
        drafter=StaticDeclarationDrafter(),
        ledger=store,
    )
    decl_store.save(
        outcome.candidate,
        acceptance_state="proposed",
        forward_verdict=outcome.forward_verdict,
        backward_verdict=outcome.backward_verdict,
        refusal_reason_code=outcome.refusal_reason_code,
    )
    from capsule_ledger.setup.confirm import ConfirmError

    with pytest.raises(ConfirmError, match="REFUSED"):
        confirm_accept(outcome_id, store=decl_store, ledger=store, signer=signer, operator="op", developer="dev")
