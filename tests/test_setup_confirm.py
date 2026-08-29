# SPDX-License-Identifier: Apache-2.0
import io

import pytest

from capsule_ledger.judge.prompt_compiler import PackContextBlock, compile_judge_prompt
from capsule_ledger.packs.schema import Outcome
from capsule_ledger.setup.confirm import (
    EVENT_JUDGE_PROMPT_CONFIRMED,
    EVENT_REFUSAL_ACKNOWLEDGED,
    ConfirmError,
    confirm_accept,
    confirm_acknowledge_refusal,
    confirm_prompt,
    confirm_scope_census,
)
from capsule_ledger.setup.declarations import DeclarationStore
from capsule_ledger.setup.observe import ObserveRecorder
from capsule_ledger.setup.propose import persist_proposals, propose_from_ledger

REMEDIATION_EVENTS = [
    {"kind": "dispatch", "dispatch_id": "d1", "action_class": "remediation", "tool": "remediate"},
    {"kind": "confirmation", "commitment_ref": "d1", "status": "confirmed"},
]

PACK_FRAMING = (
    "This pack governs a read-only investigation agent: it may query and read customer "
    "records but must never write, modify, or delete one."
)


def _observe(store, signer, events):
    recorder = ObserveRecorder(
        ledger=store, signer=signer, operator="op", developer="dev", heartbeat_every=0, heartbeat_stream=io.StringIO()
    )
    return recorder.run(events)


def _proposed_store(store, signer, tmp_path, events=()):
    _observe(store, signer, events)
    proposal_set = propose_from_ledger(store)
    decl_store = DeclarationStore(tmp_path)
    persist_proposals(proposal_set, decl_store)
    return decl_store


def _generated_prompt(outcome_id="outcome.remediation_confirmed"):
    outcome = Outcome(
        id=outcome_id,
        statement="The flagged condition was remediated.",
        evidence_rule="fulfill capsule chained to intent, effect_attestation=counterparty_confirmed",
        forward_verdict="DETERMINISTIC",
        backward_verdict="DETERMINISTIC",
    )
    pack_context = PackContextBlock(pack_id="asg/test-pack/1.0.0", framing=PACK_FRAMING)
    return compile_judge_prompt(outcome, pack_context)


def test_confirm_accept_seals_a_compilation_record_and_flips_state(store, signer, tmp_path):
    decl_store = _proposed_store(store, signer, tmp_path, REMEDIATION_EVENTS)
    assert decl_store.load("outcome.remediation_confirmed").acceptance_state == "proposed"

    record = confirm_accept("outcome.remediation_confirmed", store=decl_store, ledger=store, signer=signer, operator="op", developer="dev")
    assert record["asg_payload"]["detail"]["d_digest"] == decl_store.load("outcome.remediation_confirmed").d_digest
    assert decl_store.load("outcome.remediation_confirmed").acceptance_state == "accepted"


def test_confirm_accept_refuses_a_refused_candidate(store, signer, tmp_path):
    decl_store = _proposed_store(store, signer, tmp_path)
    with pytest.raises(ConfirmError, match="REFUSED"):
        confirm_accept("outcome.trust_increased", store=decl_store, ledger=store, signer=signer, operator="op", developer="dev")


def test_confirm_scope_census_appends_a_census_capsule(store, signer):
    capsule = confirm_scope_census(
        document_digest="d" * 64, n=3, m=5, review_by="alice", ledger=store, signer=signer, operator="op", developer="dev"
    )
    assert store.fetch(capsule["capsule_id"]) is not None


def test_confirm_acknowledge_refusal_seals_refusal_and_ack_chained(store, signer, tmp_path):
    decl_store = _proposed_store(store, signer, tmp_path)
    refusal_capsule, ack_capsule = confirm_acknowledge_refusal(
        "outcome.trust_increased", store=decl_store, ledger=store, signer=signer, operator="op", developer="dev", acknowledged_by="alice"
    )
    assert ack_capsule["chain"]["parent_capsule_id"] == refusal_capsule["capsule_id"]
    assert ack_capsule["chain"]["relation"] == "confirms"
    assert ack_capsule["asg_payload"]["event"] == EVENT_REFUSAL_ACKNOWLEDGED
    assert decl_store.load("outcome.trust_increased").acceptance_state == "refused"


def test_confirm_acknowledge_refusal_rejects_a_non_refused_candidate(store, signer, tmp_path):
    decl_store = _proposed_store(store, signer, tmp_path, REMEDIATION_EVENTS)
    with pytest.raises(ConfirmError, match="not REFUSED"):
        confirm_acknowledge_refusal(
            "outcome.remediation_confirmed", store=decl_store, ledger=store, signer=signer, operator="op", developer="dev", acknowledged_by="alice"
        )


# -- T3: judge-prompt confirmation ----------------------------------------


def test_confirm_prompt_seals_a_verifiable_capsule_chained_to_c(store, signer, tmp_path):
    decl_store = _proposed_store(store, signer, tmp_path, REMEDIATION_EVENTS)
    c_record = confirm_accept("outcome.remediation_confirmed", store=decl_store, ledger=store, signer=signer, operator="op", developer="dev")

    generated = _generated_prompt()
    capsule = confirm_prompt(
        "outcome.remediation_confirmed",
        generated_prompt=generated,
        decision="confirm",
        compilation_record_capsule_id=c_record["capsule_id"],
        ledger=store,
        signer=signer,
        operator="op",
        developer="dev",
        store=decl_store,
    )

    assert capsule["chain"]["parent_capsule_id"] == c_record["capsule_id"]
    assert capsule["chain"]["relation"] == "confirms"
    assert capsule["asg_payload"]["event"] == EVENT_JUDGE_PROMPT_CONFIRMED
    assert capsule["asg_payload"]["detail"]["prompt_digest"] == generated.prompt_digest()
    assert capsule["asg_payload"]["detail"]["instructions"] == generated.instructions
    assert capsule["asg_payload"]["detail"]["edited"] is False
    assert store.fetch(capsule["capsule_id"]) is not None
    # T3's sealed capsule must be offline-verifiable, not merely fetchable --
    # a stored-but-unverifiable record isn't the invariant confirm_prompt promises.
    assert store.verify(capsule["capsule_id"]).ok


def test_confirm_prompt_review_edit_reseals_with_the_edited_digest(store, signer, tmp_path):
    decl_store = _proposed_store(store, signer, tmp_path, REMEDIATION_EVENTS)
    c_record = confirm_accept("outcome.remediation_confirmed", store=decl_store, ledger=store, signer=signer, operator="op", developer="dev")
    generated = _generated_prompt()

    confirmed = confirm_prompt(
        "outcome.remediation_confirmed",
        generated_prompt=generated,
        decision="confirm",
        compilation_record_capsule_id=c_record["capsule_id"],
        ledger=store,
        signer=signer,
        operator="op",
        developer="dev",
        store=decl_store,
    )
    edited = confirm_prompt(
        "outcome.remediation_confirmed",
        generated_prompt=generated,
        decision="review_edit",
        edited_instructions="A rewritten, human-edited instructions block.",
        compilation_record_capsule_id=c_record["capsule_id"],
        ledger=store,
        signer=signer,
        operator="op",
        developer="dev",
        store=decl_store,
    )

    assert edited["asg_payload"]["detail"]["edited"] is True
    assert edited["asg_payload"]["detail"]["instructions"] == "A rewritten, human-edited instructions block."
    assert edited["asg_payload"]["detail"]["prompt_digest"] != confirmed["asg_payload"]["detail"]["prompt_digest"]
    # prompt_id/label_set carry over unchanged -- an edit is a wording
    # correction, never a silent re-scoping of what the prompt is for.
    assert edited["asg_payload"]["detail"]["prompt_id"] == confirmed["asg_payload"]["detail"]["prompt_id"]
    assert edited["asg_payload"]["detail"]["label_set"] == confirmed["asg_payload"]["detail"]["label_set"]


def test_confirm_prompt_review_edit_requires_edited_instructions(store, signer, tmp_path):
    decl_store = _proposed_store(store, signer, tmp_path, REMEDIATION_EVENTS)
    c_record = confirm_accept("outcome.remediation_confirmed", store=decl_store, ledger=store, signer=signer, operator="op", developer="dev")
    with pytest.raises(ConfirmError, match="review_edit"):
        confirm_prompt(
            "outcome.remediation_confirmed",
            generated_prompt=_generated_prompt(),
            decision="review_edit",
            compilation_record_capsule_id=c_record["capsule_id"],
            ledger=store,
            signer=signer,
            operator="op",
            developer="dev",
            store=decl_store,
        )


def test_confirm_prompt_confirm_rejects_stray_edited_instructions(store, signer, tmp_path):
    decl_store = _proposed_store(store, signer, tmp_path, REMEDIATION_EVENTS)
    c_record = confirm_accept("outcome.remediation_confirmed", store=decl_store, ledger=store, signer=signer, operator="op", developer="dev")
    with pytest.raises(ConfirmError, match="edited_instructions"):
        confirm_prompt(
            "outcome.remediation_confirmed",
            generated_prompt=_generated_prompt(),
            decision="confirm",
            edited_instructions="should not be set here",
            compilation_record_capsule_id=c_record["capsule_id"],
            ledger=store,
            signer=signer,
            operator="op",
            developer="dev",
            store=decl_store,
        )


def test_confirm_prompt_rejects_an_unrecognized_decision(store, signer, tmp_path):
    decl_store = _proposed_store(store, signer, tmp_path, REMEDIATION_EVENTS)
    c_record = confirm_accept("outcome.remediation_confirmed", store=decl_store, ledger=store, signer=signer, operator="op", developer="dev")
    with pytest.raises(ConfirmError, match="decision"):
        confirm_prompt(
            "outcome.remediation_confirmed",
            generated_prompt=_generated_prompt(),
            decision="approve",
            compilation_record_capsule_id=c_record["capsule_id"],
            ledger=store,
            signer=signer,
            operator="op",
            developer="dev",
            store=decl_store,
        )


def test_confirm_prompt_refuses_when_outcome_not_yet_accepted(store, signer, tmp_path):
    # T1 (confirm_accept) never ran -- the outcome is still "proposed".
    decl_store = _proposed_store(store, signer, tmp_path, REMEDIATION_EVENTS)
    with pytest.raises(ConfirmError, match="not yet accepted"):
        confirm_prompt(
            "outcome.remediation_confirmed",
            generated_prompt=_generated_prompt(),
            decision="confirm",
            compilation_record_capsule_id="c" * 64,
            ledger=store,
            signer=signer,
            operator="op",
            developer="dev",
            store=decl_store,
        )
