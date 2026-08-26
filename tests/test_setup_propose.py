# SPDX-License-Identifier: Apache-2.0
import io

from capsule_ledger.setup.declarations import DeclarationStore
from capsule_ledger.setup.observe import ObserveRecorder
from capsule_ledger.setup.propose import (
    diff_against_stored,
    observed_action_classes,
    persist_proposals,
    propose_from_census,
    propose_from_ledger,
    render_terminal,
    write_proposals_yaml,
)


def _observe(store, signer, events):
    recorder = ObserveRecorder(
        ledger=store, signer=signer, operator="op", developer="dev", heartbeat_every=0, heartbeat_stream=io.StringIO()
    )
    return recorder.run(events)


def test_attainment_candidate_absent_when_never_observed(store, signer):
    """No 'remediation' dispatch ever recorded -> the attainment candidate
    is not proposed at all (design §5's advisory-only deployment: the
    claim simply cannot be made, not made-and-failing)."""
    _observe(store, signer, [{"kind": "offer", "offer_id": "advisory/1", "offer_digest": "a" * 64}])
    proposal_set = propose_from_ledger(store)
    outcome_ids = {p.outcome_id for p in proposal_set.proposals}
    assert "outcome.remediation_confirmed" not in outcome_ids


def test_attainment_coverage_is_n_of_m_never_a_bare_percentage(store, signer):
    events = []
    for i in range(1, 6):
        events.append({"kind": "dispatch", "dispatch_id": f"d{i}", "action_class": "remediation", "tool": "remediate"})
    for i in (1, 2):
        events.append({"kind": "confirmation", "commitment_ref": f"d{i}", "status": "confirmed"})
    _observe(store, signer, events)
    proposal_set = propose_from_ledger(store)
    outcome = next(p for p in proposal_set.proposals if p.outcome_id == "outcome.remediation_confirmed")
    assert outcome.coverage_n == 2
    assert outcome.coverage_m == 5
    assert outcome.forward_verdict == "DETERMINISTIC"
    assert outcome.backward_verdict == "DETERMINISTIC"


def test_offer_response_downgrades_to_with_instrumentation_when_negative_case_never_recorded(store, signer):
    events = [
        {"kind": "offer", "offer_id": "advisory/1", "offer_digest": "a" * 64},
        {"kind": "response", "offer_id": "advisory/1", "response_class": "accepted"},
    ]
    _observe(store, signer, events)
    proposal_set = propose_from_ledger(store)
    outcome = next(p for p in proposal_set.proposals if p.outcome_id == "outcome.person_chose")
    assert outcome.backward_verdict == "WITH-INSTRUMENTATION"
    assert outcome.forward_verdict == "UNAVAILABLE-STATE-REQUIRED"
    assert outcome.missing_instrument == "decline_event"
    assert "MISSING INSTRUMENT" in outcome.rationale


def test_offer_response_upgrades_to_deterministic_once_negative_case_is_instrumented(store, signer):
    events = [
        {"kind": "offer", "offer_id": "advisory/1", "offer_digest": "a" * 64},
        {"kind": "response", "offer_id": "advisory/1", "response_class": "accepted"},
        {"kind": "offer", "offer_id": "advisory/2", "offer_digest": "b" * 64},
        {"kind": "response", "offer_id": "advisory/2", "response_class": "declined"},
    ]
    _observe(store, signer, events)
    proposal_set = propose_from_ledger(store)
    outcome = next(p for p in proposal_set.proposals if p.outcome_id == "outcome.person_chose")
    assert outcome.backward_verdict == "DETERMINISTIC"
    assert outcome.missing_instrument is None
    assert outcome.coverage_n == 1
    assert outcome.coverage_m == 2


def test_refused_candidates_always_present_and_corpus_independent(store, signer):
    _observe(store, signer, [])
    proposal_set = propose_from_ledger(store)
    refused_ids = {p.outcome_id for p in proposal_set.proposals if p.is_refused}
    assert refused_ids == {"outcome.trust_increased", "outcome.agent_resolved_case"}
    reason_codes = {p.refusal_reason_code for p in proposal_set.proposals if p.is_refused}
    assert reason_codes == {"unbounded_goal_unmonitorable", "agent_caused_resolution_undecomposable"}


def test_render_terminal_uses_status_glyphs_for_all_three_kinds(store, signer):
    events = [
        {"kind": "dispatch", "dispatch_id": "d1", "action_class": "remediation", "tool": "remediate"},
        {"kind": "confirmation", "commitment_ref": "d1", "status": "confirmed"},
    ]
    _observe(store, signer, events)
    proposal_set = propose_from_ledger(store)
    text = render_terminal(proposal_set)
    assert "✓ outcome.remediation_confirmed" in text
    assert "✗ outcome.trust_increased" in text


def test_render_terminal_uses_plain_english_verdicts_not_raw_tokens(store, signer):
    """The terminal preview must speak the same plain English the closed
    vocabulary already ships (``compiler/vocabulary.py``'s display
    strings) -- not the raw ``DETERMINISTIC``/``REFUSED`` enum tokens, which
    are undefined anywhere a stranger reading the output would see."""
    events = [
        {"kind": "dispatch", "dispatch_id": "d1", "action_class": "remediation", "tool": "remediate"},
        {"kind": "confirmation", "commitment_ref": "d1", "status": "confirmed"},
    ]
    _observe(store, signer, events)
    proposal_set = propose_from_ledger(store)
    text = render_terminal(proposal_set)
    assert "checked automatically before the action ran" in text
    assert "provable from the record alone" in text
    assert "backward DETERMINISTIC" not in text
    assert "forward DETERMINISTIC" not in text


def test_coverage_fraction_names_what_m_counts(store, signer):
    """'provable on 1 of 1' never says 1 of 1 *what* -- the denominator
    must carry a noun (dispatches/offers/decisions) so it reads as a
    stranger's sentence, not a bare fraction they have to guess the units
    of."""
    events = [
        {"kind": "dispatch", "dispatch_id": "d1", "action_class": "remediation", "tool": "remediate"},
        {"kind": "confirmation", "commitment_ref": "d1", "status": "confirmed"},
    ]
    _observe(store, signer, events)
    proposal_set = propose_from_ledger(store)
    remediation = next(p for p in proposal_set.proposals if p.outcome_id == "outcome.remediation_confirmed")
    assert remediation.coverage_fraction() == "1 of 1 dispatches (100%)"


def test_write_proposals_yaml_round_trips(store, signer, tmp_path):
    _observe(store, signer, [])
    proposal_set = propose_from_ledger(store)
    out = tmp_path / "proposals.yaml"
    write_proposals_yaml(out, proposal_set)
    import yaml

    data = yaml.safe_load(out.read_text())
    assert data["records_observed"] == 0
    assert len(data["proposals"]) == 2  # only the two REFUSED candidates observe-independent


def test_diff_against_stored_is_clean_when_nothing_changed(store, signer, tmp_path):
    _observe(store, signer, [])
    proposal_set = propose_from_ledger(store)
    decl_store = DeclarationStore(tmp_path)
    persist_proposals(proposal_set, decl_store)

    proposal_set_2 = propose_from_ledger(store)
    drift = diff_against_stored(proposal_set_2, decl_store)
    assert drift
    assert all(not d.drifted for d in drift)


def test_diff_against_stored_detects_a_planted_drift(store, signer, tmp_path):
    """The acceptance-critical mutant: hand-edit a stored candidate's own
    fields after it was proposed (simulating a template widened without
    going back through confirm) and prove the diff catches it."""
    _observe(store, signer, [])
    proposal_set = propose_from_ledger(store)
    decl_store = DeclarationStore(tmp_path)
    persist_proposals(proposal_set, decl_store)

    # Plant the drift: freeze the outcome as ACCEPTED with its current
    # (correct) candidate, then widen the underlying template so the NEXT
    # propose run computes different bytes for the same outcome_id.
    decl_store.set_acceptance_state("outcome.trust_increased", "accepted")

    import dataclasses

    import capsule_ledger.setup.candidates as candidates_mod

    original_candidates = candidates_mod.DEFAULT_CANDIDATES
    mutated = tuple(
        dataclasses.replace(c, statement="MUTATED STATEMENT")
        if c.outcome_id == "outcome.trust_increased"
        else c
        for c in original_candidates
    )
    proposal_set_mutated = propose_from_ledger(store, candidates=mutated)
    drift = diff_against_stored(proposal_set_mutated, decl_store)
    entry = next(d for d in drift if d.outcome_id == "outcome.trust_increased")
    assert entry.drifted is True

    # Falsify: re-running with the ORIGINAL (unmutated) template must be clean again.
    proposal_set_restored = propose_from_ledger(store, candidates=original_candidates)
    drift_restored = diff_against_stored(proposal_set_restored, decl_store)
    entry_restored = next(d for d in drift_restored if d.outcome_id == "outcome.trust_increased")
    assert entry_restored.drifted is False


def test_persist_proposals_never_overwrites_an_accepted_candidate(store, signer, tmp_path):
    _observe(store, signer, [])
    proposal_set = propose_from_ledger(store)
    decl_store = DeclarationStore(tmp_path)
    persist_proposals(proposal_set, decl_store)
    decl_store.set_acceptance_state("outcome.trust_increased", "accepted")
    frozen_digest = decl_store.load("outcome.trust_increased").d_digest

    # Re-running propose+persist (fresh traces) must not silently re-freeze
    # an already-accepted outcome, even though nothing here actually changed.
    proposal_set_2 = propose_from_ledger(store)
    persist_proposals(proposal_set_2, decl_store)
    assert decl_store.load("outcome.trust_increased").acceptance_state == "accepted"
    assert decl_store.load("outcome.trust_increased").d_digest == frozen_digest


# --- census: acceptance addendum item 2 -------------------------------------
# "Census is the chunk-2 core, not a nice-to-have -- grading currently runs
# only over static DEFAULT_CANDIDATES; an observed-action_class enumeration
# over the corpus is required for the pack-first walk to demo."


def test_census_enumerates_observed_action_classes_from_the_corpus(store, signer):
    """'refund' is dispatched but named by NO ``DEFAULT_CANDIDATES`` entry
    -- the census must surface it directly from the corpus, not from the
    hardcoded catalog."""
    events = [{"kind": "dispatch", "dispatch_id": "d1", "action_class": "refund", "tool": "issue_refund"}]
    _observe(store, signer, events)
    assert observed_action_classes(store) == {"refund"}


def test_census_grading_includes_an_action_class_absent_from_default_candidates(store, signer):
    """DEFAULT_CANDIDATES alone never proposes anything for 'refund';
    census-based grading must, proving grading runs over what is actually
    observed rather than only the hardcoded default list."""
    events = [{"kind": "dispatch", "dispatch_id": "d1", "action_class": "refund", "tool": "issue_refund"}]
    _observe(store, signer, events)

    baseline = propose_from_ledger(store)
    assert not any(getattr(p.candidate, "action_class", None) == "refund" for p in baseline.proposals)

    census_set = propose_from_census(store)
    refund_proposals = [p for p in census_set.proposals if getattr(p.candidate, "action_class", None) == "refund"]
    assert len(refund_proposals) == 1
    assert refund_proposals[0].coverage_n == 0
    assert refund_proposals[0].coverage_m == 1


def test_census_grading_still_includes_every_default_candidate(store, signer):
    """Census-based grading is additive -- it must not drop any of the
    catalog's own candidates, including the corpus-independent REFUSED
    ones."""
    _observe(store, signer, [])
    census_set = propose_from_census(store)
    outcome_ids = {p.outcome_id for p in census_set.proposals}
    assert {"outcome.trust_increased", "outcome.agent_resolved_case"} <= outcome_ids
