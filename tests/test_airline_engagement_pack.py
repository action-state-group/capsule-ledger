# SPDX-License-Identifier: Apache-2.0
"""``[ldg-airline-engagement-pack]``: A1-A8's pack semantics, plus the
acceptance criteria stated verbatim in inbox.md --

- every row renders a display string that does not assert a feeling
- A1's guard shown refusing a one-option offer, and shown RED (firing) when
  the guard is removed (the guard itself, and its RED/GREEN pair, lives in
  ``test_compiler_offer_response.py`` -- this module additionally proves the
  pack's own A1 row is wired to that exact primitive, not a re-implementation)
- A8's refusal fires
- the WITH-INSTRUMENTATION row (A3a) names a real absent instrument
- the pack reports the actual measured N-of-M, whatever it is
"""
from __future__ import annotations

import hashlib
import re

import pytest

from capsule_ledger.compiler.offer_response import (
    ChoiceClaimRequiresMultipleOptions,
    build_offer_capsule,
    build_response_capsule,
)
from capsule_ledger.compiler.refusal import EVENT_REFUSAL
from capsule_ledger.compiler.vocabulary import RESERVED_VERDICT_WORDS
from capsule_ledger.examples.airline_engagement_pack import (
    DATA_FILE,
    AirlineClaimResult,
    _asks_for_human,
    build_a8_satisfaction_refusal,
    build_airline_engagement_pack,
    load_conversations,
    measure_a4_human_reachable_when_asked,
    measure_a6_resolved_without_transfer,
    measure_a7_pushback_present,
    render_terminal,
)

OPERATOR = "test-operator"
DEVELOPER = "test-developer@v1"

# A rendered claim's display_line() must never assert that a feeling was
# experienced as fact -- the acceptance line's own vocabulary, checked
# directly rather than paraphrased.
_FEELING_ASSERTION_WORDS = ("satisfied", "felt", "happy", "trust increased", "comfortable")


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.fixture(scope="module")
def pack():
    return build_airline_engagement_pack()


# --- structural: every row is a real, closed-vocabulary verdict pair -------


def test_pack_has_exactly_the_nine_declared_rows(pack):
    assert [r.claim_id for r in pack.rows] == ["A1", "A2", "A3a", "A3b", "A4", "A5", "A6", "A7", "A8"]


def test_a6_and_a7_declare_no_forward_verdict(pack):
    by_id = {r.claim_id: r for r in pack.rows}
    assert by_id["A6"].forward_verdict is None
    assert by_id["A7"].forward_verdict is None


def test_a1_forward_stays_deterministic_backward_is_with_instrumentation(pack):
    """``[ldg-bj-91-a1-to-llm-judge]`` (review bounce B2): A1's backward
    verdict used to render DETERMINISTIC off a regex grepping free text --
    that was the mislabel this bounce fixes. Forward is untouched: the
    ``ChoiceClaimRequiresMultipleOptions`` guard is a real, separate
    mechanism this bounce does not touch."""
    by_id = {r.claim_id: r for r in pack.rows}
    assert by_id["A1"].forward_verdict == "DETERMINISTIC"
    assert by_id["A1"].backward_verdict == "WITH-INSTRUMENTATION"


def test_a4_and_a6_statements_do_not_overclaim(pack):
    """Retuned, [ldg-airline-pack-semantics-tuning]: 'always reachable' and
    'resolved' both overclaimed what a <100% ratio / a tool-call-absence
    check can prove. Locking the renamed wording so a future edit can't
    silently revert to the overclaiming statement."""
    by_id = {r.claim_id: r for r in pack.rows}
    assert "always" not in by_id["A4"].statement.lower()
    assert by_id["A4"].statement == "A human on request: when the customer asked for a person, one was reachable."
    assert "resolved" not in by_id["A6"].statement.lower()
    assert by_id["A6"].statement == "Handled, not offloaded: the case was handled without transfer to a human."


def test_an_invalid_verdict_pair_is_rejected():
    with pytest.raises(ValueError):
        AirlineClaimResult(
            claim_id="AX",
            statement="not a real closed-set value",
            forward_verdict="MAYBE",
            backward_verdict="DETERMINISTIC",
            coverage_n=None,
            coverage_m=None,
            rationale="mutant proof",
        )


# --- acceptance: no row's rendered display string asserts a feeling --------


def test_no_row_display_line_asserts_a_feeling(pack):
    for row in pack.rows:
        line = row.display_line().lower()
        for word in _FEELING_ASSERTION_WORDS:
            assert word not in line, f"{row.claim_id} display_line asserts a feeling via {word!r}: {line!r}"


def test_no_row_display_line_carries_a_reserved_verdict_word(pack):
    for row in pack.rows:
        line = row.display_line().lower()
        for word in RESERVED_VERDICT_WORDS:
            assert word not in line, f"{row.claim_id} display_line carries the reserved word {word!r}: {line!r}"


# --- A8: the refusal fires --------------------------------------------------


def test_a8_refusal_fires(pack):
    by_id = {r.claim_id: r for r in pack.rows}
    a8 = by_id["A8"]
    assert a8.forward_verdict == "REFUSED"
    assert a8.backward_verdict == "REFUSED"
    assert a8.refusal_reason_code == "subjective_state_unattestable"

    cap = pack.a8_refusal_capsule
    assert cap["asg_payload"]["event"] == EVENT_REFUSAL
    detail = cap["asg_payload"]["detail"]
    assert detail["verdict_class"] == {"forward": "REFUSED", "backward": "REFUSED"}
    assert detail["reason_code"] == "subjective_state_unattestable"


def test_a8_refusal_capsule_is_reproducible_standalone(signer):
    cap = build_a8_satisfaction_refusal(
        statement_digest=_digest("A8: the customer was satisfied"),
        operator=OPERATOR,
        developer=DEVELOPER,
        signer=signer,
    )
    assert cap["asg_payload"]["detail"]["reason_code"] == "subjective_state_unattestable"


# --- A3a: the WITH-INSTRUMENTATION row names a real absent instrument ------


def test_a3a_is_with_instrumentation_and_names_a_real_missing_instrument(pack):
    by_id = {r.claim_id: r for r in pack.rows}
    a3a = by_id["A3a"]
    assert a3a.backward_verdict == "WITH-INSTRUMENTATION"
    assert a3a.missing_instrument == "typed_severity_efficacy_label"
    # a slug-shaped name, not a sentence -- same "no free prose" discipline
    # refusal.py's own labelled items enforce
    assert a3a.missing_instrument.replace("_", "").isalnum()
    assert " " not in a3a.missing_instrument


def test_a3a_forward_verdict_matches_a2_and_a5_missing_instrument_pattern(pack):
    """Retuned, [ldg-airline-pack-semantics-tuning]: A3a used to render
    forward DETERMINISTIC while its own rationale said the deterministic
    rule has nothing to run over on this dataset -- a self-contradiction.
    A2 and A5 already render UNAVAILABLE-STATE-REQUIRED for exactly this
    "missing typed record" situation; A3a now matches them."""
    by_id = {r.claim_id: r for r in pack.rows}
    a2, a3a, a5 = by_id["A2"], by_id["A3a"], by_id["A5"]
    assert a3a.forward_verdict == "UNAVAILABLE-STATE-REQUIRED"
    assert a3a.forward_verdict == a2.forward_verdict == a5.forward_verdict


# --- A1: the keyword stand-in was removed; renders WITH-INSTRUMENTATION ----
# [ldg-bj-91-a1-to-llm-judge] (review bounce B2 on [remove-keyword-scorers]):
# A1's backward side used to report a deterministic keyword regex's count as
# if it were a structural fact. "More than one viable path" is a
# prose-quality judgment, the same shape as A3b's "no pressure" -- the row
# now renders pending a real judge run, with a real compiled prompt digest
# already pinned, never a fabricated number.


def test_a1_no_longer_reports_a_measured_count(pack):
    by_id = {r.claim_id: r for r in pack.rows}
    a1 = by_id["A1"]
    assert a1.forward_verdict == "DETERMINISTIC"
    assert a1.backward_verdict == "WITH-INSTRUMENTATION"
    assert a1.coverage_n is None
    assert a1.coverage_m is None
    assert a1.coverage_fraction() is None
    assert a1.missing_instrument == "llm_judge_verdict_a1_option_language"
    assert a1.needs_instrumentation is True


def test_a1_carries_a_real_compiled_judge_prompt_digest(pack):
    """The differentiator from A3b's plainer pending state (Steven's
    ruling, inbox.md): A1's row cites a REAL, compiled
    ``JudgePromptDefinition.prompt_digest()`` (``compile_judge_prompt``, PR
    #90), not merely a rationale describing what would eventually run."""
    by_id = {r.claim_id: r for r in pack.rows}
    a1 = by_id["A1"]
    assert a1.judge_prompt_digest is not None
    assert len(a1.judge_prompt_digest) == 64  # sha256 hex digest
    assert all(c in "0123456789abcdef" for c in a1.judge_prompt_digest)
    assert a1.judge_prompt_digest in a1.rationale


def test_a1_rationale_names_the_removed_mechanism_not_a_number():
    """Mutant proof: a regression that reintroduces a coverage_n/coverage_m
    pair for A1 (e.g. someone re-wires the old regex back in) would make
    this row's coverage_fraction() non-None again, which the test above
    catches; this test separately locks that the rationale text itself
    never carries a bare 'N of M' shape a reader could mistake for a real
    measurement."""
    pack = build_airline_engagement_pack()
    by_id = {r.claim_id: r for r in pack.rows}
    rationale = by_id["A1"].rationale
    assert "MISSING INSTRUMENT" in rationale
    assert not re.search(r"\b\d+ of \d+\b", rationale)


def test_module_no_longer_exposes_the_a1_keyword_regex():
    """[ldg-bj-91-a1-to-llm-judge] acceptance: the keyword stand-in this row
    used to render is gone from the module entirely, not merely unused."""
    import capsule_ledger.examples.airline_engagement_pack as mod

    assert not hasattr(mod, "_OPTION_LANGUAGE_RE")
    assert not hasattr(mod, "measure_a1_option_shaped_language")


# --- A3b: the keyword stand-in was removed; renders WITH-INSTRUMENTATION ---
# [remove-keyword-scorers]: A3b used to report a deterministic keyword
# regex's count as if it were a MODEL-ASSISTED finding. "No pressure" is a
# prose-quality judgment, not a structural event a regex can honestly stand
# in for -- the row now renders pending a real judge run, never a fabricated
# number.


def test_a3b_no_longer_reports_a_measured_count(pack):
    by_id = {r.claim_id: r for r in pack.rows}
    a3b = by_id["A3b"]
    assert a3b.forward_verdict == "UNAVAILABLE-MODEL-REQUIRED"
    assert a3b.backward_verdict == "WITH-INSTRUMENTATION"
    assert a3b.coverage_n is None
    assert a3b.coverage_m is None
    assert a3b.coverage_fraction() is None
    assert a3b.missing_instrument == "llm_judge_verdict_a3b_pressure_language"
    assert a3b.needs_instrumentation is True


def test_a3b_rationale_names_the_removed_mechanism_not_a_number():
    """Mutant proof: a regression that reintroduces a coverage_n/coverage_m
    pair for A3b (e.g. someone re-wires the old regex back in) would make
    this row's coverage_fraction() non-None again, which the test above
    catches; this test separately locks that the rationale text itself
    never carries a bare 'N of M' shape a reader could mistake for a real
    measurement."""
    pack = build_airline_engagement_pack()
    by_id = {r.claim_id: r for r in pack.rows}
    rationale = by_id["A3b"].rationale
    assert "MISSING INSTRUMENT" in rationale
    assert not re.search(r"\b\d+ of \d+\b", rationale)


def test_module_no_longer_exposes_the_a3b_keyword_regex():
    """[remove-keyword-scorers] acceptance: the keyword stand-in this row
    used to render is gone from the module entirely, not merely unused."""
    import capsule_ledger.examples.airline_engagement_pack as mod

    assert not hasattr(mod, "_PRESSURE_LANGUAGE_RE")
    assert not hasattr(mod, "measure_a3b_pressure_language_absent")


# --- A1's own guard: refuses a one-option offer, RED when removed ----------


def test_a1_guard_refuses_a_one_option_offer(signer):
    """The exact primitive A1's forward side reports on
    (ChoiceClaimRequiresMultipleOptions) -- proved firing here so this
    pack's own test suite carries the RED case, not only
    test_compiler_offer_response.py's."""
    one_option = [_digest("option-a")]
    offer = build_offer_capsule(
        offer_id="offer-1",
        offer_digest=_digest("offer"),
        option_digests=one_option,
        operator=OPERATOR,
        developer=DEVELOPER,
        signer=signer,
    )
    with pytest.raises(ChoiceClaimRequiresMultipleOptions):
        build_response_capsule(
            offer_id="offer-1",
            offer_capsule_id=offer["capsule_id"],
            response_class="accepted",
            operator=OPERATOR,
            developer=DEVELOPER,
            signer=signer,
            selected_option_digest=one_option[0],
            offer_option_digests=one_option,
        )


def test_a1_guard_is_GREEN_once_a_second_option_exists(signer):
    """The RED case above turns GREEN by widening option_count from 1 to 2
    and nothing else -- the mutant proof: a guard that had been neutered
    (e.g. the < 2 check silently removed) would let the RED case above pass
    too, so the pair together is what proves the guard is live."""
    two_options = [_digest("option-a"), _digest("option-b")]
    offer = build_offer_capsule(
        offer_id="offer-1",
        offer_digest=_digest("offer"),
        option_digests=two_options,
        operator=OPERATOR,
        developer=DEVELOPER,
        signer=signer,
    )
    response = build_response_capsule(
        offer_id="offer-1",
        offer_capsule_id=offer["capsule_id"],
        response_class="accepted",
        operator=OPERATOR,
        developer=DEVELOPER,
        signer=signer,
        selected_option_digest=two_options[0],
        offer_option_digests=two_options,
    )
    assert response["asg_payload"]["detail"]["selected_option_digest"] == two_options[0]


# --- retuned classifiers, synthetic strings, corpus-independent ------------
# [ldg-airline-pack-semantics-tuning]: fast regression tests for the exact
# false-positive/false-negative shapes the adversarial re-evaluation found,
# independent of the vendored file (so they still catch a regex regression
# even if the corpus is ever re-vendored). A1's own regex tests were removed
# by [ldg-bj-91-a1-to-llm-judge] along with ``_OPTION_LANGUAGE_RE`` itself --
# see ``test_module_no_longer_exposes_the_a1_keyword_regex`` above.


def test_a4_negation_guard_excludes_a_declined_transfer():
    """A customer explicitly declining a transfer is not a request for
    one -- the negation guard exists because the retuned broader vocabulary
    ("talk to someone") would otherwise fire on the decline itself."""
    text = "To be clear, I don't want to be transferred to a human agent -- I'd like you to handle this for me."
    assert not _asks_for_human(text)


def test_a4_still_catches_the_missed_transfer_phrasing():
    assert _asks_for_human("Fine, transfer me to someone who can actually help.")
    assert _asks_for_human("I'd like to talk to someone about this.")


# --- measured rows report a real N-of-M over the vendored 200-sim file -----


def test_vendored_conversation_file_has_200_simulations():
    sims = load_conversations()
    assert len(sims) == 200


@pytest.mark.parametrize(
    "measure,expected_n",
    [
        # Retuned, [ldg-airline-pack-semantics-tuning] (2026-08-22): these
        # are the actual measured, hand-verified counts on the vendored
        # file today -- NOT a target. Pinned exactly (not a range) because
        # a bare "0 < n < m" is exactly what let a regex edit that halved
        # a classifier's count ship green before: it cannot distinguish a
        # genuine hand-verified count from a heuristic that stopped firing,
        # nor can it catch a count that moved but stayed in-range. A real
        # change to a classifier's precision/recall SHOULD move this number
        # and SHOULD fail this test -- that is the point. When it's a
        # genuine, deliberate retune: re-run the hand-labelling in
        # tests/test_airline_engagement_pack_hand_labels.py, update
        # hand_labels.json, and update the expected value here together,
        # not this number alone. (A3b's own keyword stand-in and its pinned
        # 200-of-200 were removed entirely, [remove-keyword-scorers]; A1's
        # own stand-in and its pinned 111-of-200 were removed the same way,
        # [ldg-bj-91-a1-to-llm-judge] -- see
        # test_a3b_no_longer_reports_a_measured_count /
        # test_a1_no_longer_reports_a_measured_count above.)
        (measure_a6_resolved_without_transfer, 160),
        (measure_a7_pushback_present, 26),
    ],
)
def test_measured_rows_report_the_retuned_n_of_200(measure, expected_n):
    sims = load_conversations()
    n, m = measure(sims)
    assert m == 200
    assert n == expected_n


def test_a4_measures_reachability_conditioned_on_having_asked():
    """Pinned exact values, [ldg-airline-pack-semantics-tuning]: the
    denominator (23/33) was retuned and hand-verified -- same reasoning as
    ``test_measured_rows_report_the_retuned_n_of_200`` above."""
    sims = load_conversations()
    reached, asked = measure_a4_human_reachable_when_asked(sims)
    assert (reached, asked) == (23, 33)


def test_pack_rows_carry_their_measured_coverage(pack):
    by_id = {r.claim_id: r for r in pack.rows}
    for claim_id in ("A4", "A6", "A7"):
        row = by_id[claim_id]
        assert row.coverage_n is not None
        assert row.coverage_m is not None
        assert row.coverage_fraction() == f"{row.coverage_n} of {row.coverage_m}"
    for claim_id in ("A1", "A2", "A3b", "A5", "A8"):
        row = by_id[claim_id]
        assert row.coverage_n is None
        assert row.coverage_fraction() is None


def test_render_terminal_includes_every_row_and_the_refusal_capsule(pack):
    text = render_terminal(pack)
    for claim_id in ("A1", "A2", "A3a", "A3b", "A4", "A5", "A6", "A7", "A8"):
        assert claim_id in text
    assert "subjective_state_unattestable" in text


def test_data_file_exists_on_disk():
    assert DATA_FILE.exists()
