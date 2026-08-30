# SPDX-License-Identifier: Apache-2.0
"""``[ldg-bp-counterparty-change-family]``: the counterparty-change value-
props (standard-outcome-pack design §5) as a two-layer composition -- a
per-session signal (structural or judged) feeding a design §10 type-2
``counterparty_change`` fold (PR #92's ``folds/taxonomy.py``), NOT a new
judgment. End-to-end over a small multi-session fixture for C5 (growing
autonomy, structural signal) and C1 (capability growth, judged signal):
the trend runs the right direction, the min-N gate refuses below threshold,
and the fold path never invokes the judge (§10.1 invariant, asserted both
statically -- no import -- and dynamically -- the harness is never called).
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path
from unittest.mock import patch

import pytest

from capsule_ledger.folds import counterparty_signals as csig
from capsule_ledger.folds.taxonomy import CORRELATION_NOT_CAUSE_CAVEAT
from capsule_ledger.packs.loader import load_pack_dir

STANDARD_VENDOR_DIR = Path(__file__).parent.parent / "capsule_ledger" / "packs" / "catalog" / "standard-vendor"


# ---------------------------------------------------------------------------
# the §10.1 invariant: this module cannot reach the judge, statically or
# dynamically
# ---------------------------------------------------------------------------


def test_the_module_never_imports_the_judge_package():
    """Static proof: parse this module's own source and confirm no import
    statement names ``capsule_ledger.judge`` (or a relative equivalent) --
    the fold path can only avoid calling the judge if it never even holds a
    reference to it."""
    source = inspect.getsource(csig)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "judge" not in alias.name, alias.name
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert "judge" not in module, module


def test_running_a_judged_signals_trajectory_never_calls_the_judge_harness():
    """Dynamic proof: even for ``BASIC_QUESTION_COUNT`` (mode="judged"),
    feeding its already-sealed per-session capsules through
    ``counterparty_trajectory_for_signal`` must not touch ``JudgeHarness.run``
    -- the fold REDUCES OVER sealed signal capsules, it never re-scores them
    (design §10.1)."""
    from capsule_ledger.judge.harness import JudgeHarness

    records = [
        csig.signal_record(csig.BASIC_QUESTION_COUNT, session="s1", counterparty="acme", value=5),
        csig.signal_record(csig.BASIC_QUESTION_COUNT, session="s2", counterparty="acme", value=3),
        csig.signal_record(csig.BASIC_QUESTION_COUNT, session="s3", counterparty="acme", value=1),
    ]
    with patch.object(JudgeHarness, "run", side_effect=AssertionError("fold path must never call the judge")) as mocked:
        result = csig.counterparty_trajectory_for_signal(
            csig.BASIC_QUESTION_COUNT, records, counterparty="acme", min_n=3
        )
    mocked.assert_not_called()
    assert result.gated is False
    assert [p.trace.result for p in result.points] == [5, 3, 1]


# ---------------------------------------------------------------------------
# C5 growing autonomy -- structural signal (clarification-turn count)
# ---------------------------------------------------------------------------


def _session_turns(clarification_count: int, other_count: int = 2) -> list[dict]:
    turns = [{"role": "counterparty", "is_clarification": True} for _ in range(clarification_count)]
    turns += [{"role": "counterparty", "is_clarification": False} for _ in range(other_count)]
    turns += [{"role": "agent", "is_clarification": False} for _ in range(other_count)]
    return turns


def test_compute_clarification_turn_count_is_structural_and_deterministic():
    turns = _session_turns(clarification_count=3)
    assert csig.compute_clarification_turn_count(turns) == 3
    # calling it again over the same input gives the identical result -- no
    # model, no hidden state.
    assert csig.compute_clarification_turn_count(turns) == 3


def test_compute_clarification_turn_count_ignores_agent_turns_and_missing_fields():
    turns = [
        {"role": "agent", "is_clarification": True},  # not the counterparty -- excluded
        {"role": "counterparty"},  # no is_clarification field -- excluded, not an error
        {"role": "counterparty", "is_clarification": True},
    ]
    assert csig.compute_clarification_turn_count(turns) == 1


def _c5_fixture_records() -> list[dict]:
    # four sessions, clarification turns trending DOWN -- growing autonomy.
    per_session_counts = [4, 3, 1, 0]
    return [
        csig.signal_record(
            csig.CLARIFICATION_TURN_COUNT,
            session=f"s{i + 1}",
            counterparty="acme",
            value=csig.compute_clarification_turn_count(_session_turns(count)),
        )
        for i, count in enumerate(per_session_counts)
    ]


def test_c5_trajectory_trends_down_across_sessions_in_ledger_order():
    records = _c5_fixture_records()
    result = csig.counterparty_trajectory_for_signal(
        csig.CLARIFICATION_TURN_COUNT, records, counterparty="acme", min_n=3
    )
    assert result.gated is False
    assert [p.session_id for p in result.points] == ["s1", "s2", "s3", "s4"]
    values = [p.trace.result for p in result.points]
    assert values == [4, 3, 1, 0]
    assert all(earlier >= later for earlier, later in zip(values, values[1:], strict=False))
    assert result.caveat == CORRELATION_NOT_CAUSE_CAVEAT


def test_c5_trajectory_is_gated_below_min_n_with_no_points_stated():
    records = _c5_fixture_records()  # 4 sessions
    result = csig.counterparty_trajectory_for_signal(
        csig.CLARIFICATION_TURN_COUNT, records, counterparty="acme", min_n=5
    )
    assert result.gated is True
    assert result.points == ()
    assert result.engagement_count == 4
    assert result.min_n == 5


# ---------------------------------------------------------------------------
# C1 capability growth -- judged signal (basic-question count)
# ---------------------------------------------------------------------------


def _c1_fixture_records() -> list[dict]:
    # four sessions, basic-question count trending DOWN -- capability growth.
    # Each value stands in for an already-sealed judgment (design §10.1: the
    # LLM scored this BEFORE the fold ever runs).
    return [
        csig.signal_record(csig.BASIC_QUESTION_COUNT, session=f"s{i + 1}", counterparty="acme", value=v)
        for i, v in enumerate([6, 4, 2, 1])
    ]


def test_c1_trajectory_trends_down_across_sessions_in_ledger_order():
    records = _c1_fixture_records()
    result = csig.counterparty_trajectory_for_signal(
        csig.BASIC_QUESTION_COUNT, records, counterparty="acme", min_n=3
    )
    assert result.gated is False
    values = [p.trace.result for p in result.points]
    assert values == [6, 4, 2, 1]
    assert all(earlier >= later for earlier, later in zip(values, values[1:], strict=False))
    assert result.caveat == CORRELATION_NOT_CAUSE_CAVEAT


def test_c1_trajectory_is_gated_below_min_n_with_no_points_stated():
    records = _c1_fixture_records()  # 4 sessions
    result = csig.counterparty_trajectory_for_signal(
        csig.BASIC_QUESTION_COUNT, records, counterparty="acme", min_n=6
    )
    assert result.gated is True
    assert result.points == ()


# ---------------------------------------------------------------------------
# binding to the profile's counterparty (design §6b): the C-family's subject
# is whichever role the pack's topology profile names as the DIRECT
# counterparty -- this module is agnostic to which role that is, it only
# ever reduces over records the caller has already scoped to one.
# ---------------------------------------------------------------------------


def test_wiring_binds_to_the_profiles_direct_counterparty_role():
    pack = load_pack_dir(STANDARD_VENDOR_DIR)
    profiled = pack.outcomes_for_profile("p2_internal_assist")
    assert profiled.subject_for("C5") == "employee"
    assert profiled.subject_for("C1") == "employee"

    # the caller scopes records to the role the profile names before ever
    # calling this module -- here, an "employee" identity, not a "customer"
    # one, exactly what p2_internal_assist's binding says the C-family
    # subject is under this topology.
    records = [
        csig.signal_record(csig.CLARIFICATION_TURN_COUNT, session="s1", counterparty="alice", value=3),
        csig.signal_record(csig.CLARIFICATION_TURN_COUNT, session="s2", counterparty="alice", value=1),
        csig.signal_record(csig.CLARIFICATION_TURN_COUNT, session="s3", counterparty="alice", value=0),
    ]
    result = csig.counterparty_trajectory_for_signal(
        csig.CLARIFICATION_TURN_COUNT, records, counterparty="alice", min_n=3
    )
    assert result.counterparty == "alice"
    assert result.gated is False


# ---------------------------------------------------------------------------
# CounterpartySignal validation
# ---------------------------------------------------------------------------


def test_counterparty_signal_rejects_an_unknown_mode():
    with pytest.raises(ValueError):
        csig.CounterpartySignal(
            signal_id="x", feeds_outcome_id="C1", statement="s", mode="value", field="x"
        )


def test_the_two_declared_signals_feed_the_pack_rows_the_design_names():
    assert csig.CLARIFICATION_TURN_COUNT.feeds_outcome_id == "C5"
    assert csig.CLARIFICATION_TURN_COUNT.mode == "structural"
    assert csig.BASIC_QUESTION_COUNT.feeds_outcome_id == "C1"
    assert csig.BASIC_QUESTION_COUNT.mode == "judged"
    # pack.yaml's own evidence_instrument.field for C1/C5 names the TREND
    # field this fold's raw per-session signal feeds -- f"{field}_trend".
    pack = load_pack_dir(STANDARD_VENDOR_DIR)
    c1 = pack.outcome_for_id("C1")
    c5 = pack.outcome_for_id("C5")
    assert c1.evidence_instrument.field == f"{csig.BASIC_QUESTION_COUNT.field}_trend"
    assert c5.evidence_instrument.field == f"{csig.CLARIFICATION_TURN_COUNT.field}_trend"
