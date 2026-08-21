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
    build_a8_satisfaction_refusal,
    build_airline_engagement_pack,
    load_conversations,
    measure_a1_option_shaped_language,
    measure_a3b_pressure_language_absent,
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


def test_a1_is_deterministic_both_sides(pack):
    by_id = {r.claim_id: r for r in pack.rows}
    assert by_id["A1"].forward_verdict == "DETERMINISTIC"
    assert by_id["A1"].backward_verdict == "DETERMINISTIC"


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


# --- measured rows report a real N-of-M over the vendored 200-sim file -----


def test_vendored_conversation_file_has_200_simulations():
    sims = load_conversations()
    assert len(sims) == 200


@pytest.mark.parametrize(
    "measure",
    [
        measure_a1_option_shaped_language,
        measure_a3b_pressure_language_absent,
        measure_a6_resolved_without_transfer,
        measure_a7_pushback_present,
    ],
)
def test_measured_rows_report_a_real_n_of_200(measure):
    sims = load_conversations()
    n, m = measure(sims)
    assert m == 200
    # unflattering numbers are expected and untuned -- the only structural
    # requirement is a real, in-range count, never 0 or 200 flat (either
    # extreme would mean the heuristic never fires at all, or always does)
    assert 0 < n < m


def test_a4_measures_reachability_conditioned_on_having_asked():
    sims = load_conversations()
    reached, asked = measure_a4_human_reachable_when_asked(sims)
    assert asked > 0
    assert 0 <= reached <= asked


def test_pack_rows_carry_their_measured_coverage(pack):
    by_id = {r.claim_id: r for r in pack.rows}
    for claim_id in ("A1", "A3b", "A4", "A6", "A7"):
        row = by_id[claim_id]
        assert row.coverage_n is not None
        assert row.coverage_m is not None
        assert row.coverage_fraction() == f"{row.coverage_n} of {row.coverage_m}"
    for claim_id in ("A2", "A5", "A8"):
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
