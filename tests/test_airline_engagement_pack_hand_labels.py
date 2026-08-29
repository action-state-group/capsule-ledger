# SPDX-License-Identifier: Apache-2.0
"""``[ldg-airline-pack-semantics-tuning]``: precision/recall of the A1, A4
and A7 classifiers against a hand-labelled sample of >=20 conversations per
row, per the task's acceptance line.

This is the replacement for the old, too-weak
``test_measured_rows_report_a_real_n_of_200``'s bare ``0 < n < m``: that
assertion could not tell a genuine hand-verified count apart from a
heuristic that never fires at all, and a regex edit that halved A1's count
would still have shipped green. Here, ``predicted`` is recomputed LIVE
against the current regex for every hand-labelled sim_id in
``hand_labels.json`` -- a regression in any of the three classifiers
changes a ``predicted`` value and fails the matching case immediately, not
just a coarse count.

``[remove-keyword-scorers]`` (2026-08-29) dropped A3b from this module: its
keyword regex was never a classifier standing in for a structural check
(unlike A1/A4/A7, which each detect a concrete, structural event -- an
offer, a transfer request, a pushback -- in the record) -- it was a
deterministic stand-in reported as if it were a live judge's prose-quality
finding. ``hand_labels.json`` still carries its historical "A3b" section
(the hand-labelling that found the regex's 41-of-45 false-positive rate,
[ldg-airline-pack-semantics-tuning]) as a record of why it was retuned and
then removed, but nothing here reads it anymore -- see
``airline_engagement_pack.declare_a3b_pressure_language_pending_judge``
for the row's current, honest state."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from capsule_ledger.examples.airline_engagement_pack import (
    _AGENT_LIMITATION_RE,
    _OPTION_LANGUAGE_RE,
    _PUSHBACK_RE,
    DATA_FILE,
    _asks_for_human,
    _text,
    load_conversations,
)

HAND_LABELS_FILE = DATA_FILE.parent / "hand_labels.json"


@pytest.fixture(scope="module")
def sims_by_id():
    return {sim["sim_id"]: sim for sim in load_conversations()}


@pytest.fixture(scope="module")
def hand_labels():
    return json.loads(Path(HAND_LABELS_FILE).read_text())


def _predict_a1(sim):
    return any(m["role"] == "assistant" and _OPTION_LANGUAGE_RE.search(_text(m)) for m in sim["messages"])


def _predict_a4_asked(sim):
    return any(m["role"] == "user" and _asks_for_human(_text(m)) for m in sim["messages"])


def _predict_a7(sim):
    user_turn = -1
    seen_limitation = False
    for m in sim["messages"]:
        if m["role"] == "assistant":
            if _AGENT_LIMITATION_RE.search(_text(m)):
                seen_limitation = True
        elif m["role"] == "user":
            user_turn += 1
            if user_turn == 0:
                continue
            if seen_limitation and _PUSHBACK_RE.search(_text(m)):
                return True
    return False


_PREDICTORS = {
    "A1": _predict_a1,
    "A4": _predict_a4_asked,
    "A7": _predict_a7,
}

# Precision/recall floors below the CURRENT measured value on this fixture
# (see hand_labels.json's "summary" for the exact numbers) -- a regression
# that meaningfully degrades a classifier fails here; the floors are not set
# at 100% because A7's gating is documented as imperfect on purpose (see its
# docstring), not because this test tolerates drift.
_MIN_PRECISION = {"A1": 0.95, "A4": 0.95, "A7": 0.80}
_MIN_RECALL = {"A1": 0.95, "A4": 0.95, "A7": 0.70}


def test_hand_labels_file_exists_and_has_at_least_20_cases_per_row():
    data = json.loads(Path(HAND_LABELS_FILE).read_text())
    for claim_id in ("A1", "A4", "A7"):
        assert len(data[claim_id]["cases"]) >= 20, f"{claim_id} has fewer than 20 hand-labelled cases"


@pytest.mark.parametrize("claim_id", ["A1", "A4", "A7"])
def test_predicted_matches_hand_label_for_every_case(claim_id, sims_by_id, hand_labels):
    """Recompute ``predicted`` live for every hand-labelled sim_id and prove
    it still matches what was recorded when the fixture was built -- the
    live check that stops the fixture from silently going stale."""
    predictor = _PREDICTORS[claim_id]
    for case in hand_labels[claim_id]["cases"]:
        sim = sims_by_id[case["sim_id"]]
        live_predicted = predictor(sim)
        assert live_predicted == case["predicted"], (
            f"{claim_id} sim {case['sim_id']}: fixture recorded predicted={case['predicted']!r} "
            f"but the live classifier now returns {live_predicted!r} -- the regex changed since "
            f"the fixture was built; re-verify by hand and regenerate hand_labels.json, don't just "
            f"update the number"
        )


@pytest.mark.parametrize("claim_id", ["A1", "A4", "A7"])
def test_precision_meets_floor(claim_id, hand_labels):
    cases = hand_labels[claim_id]["cases"]
    tp = sum(1 for c in cases if c["hand_label"] and c["predicted"])
    fp = sum(1 for c in cases if not c["hand_label"] and c["predicted"])
    assert tp + fp > 0, f"{claim_id} has no positive predictions in the fixture -- precision is undefined"
    precision = tp / (tp + fp)
    assert precision >= _MIN_PRECISION[claim_id], f"{claim_id} precision {precision:.2%} fell below floor"


@pytest.mark.parametrize("claim_id", ["A1", "A4", "A7"])
def test_recall_meets_floor(claim_id, hand_labels):
    cases = hand_labels[claim_id]["cases"]
    tp = sum(1 for c in cases if c["hand_label"] and c["predicted"])
    fn = sum(1 for c in cases if c["hand_label"] and not c["predicted"])
    assert tp + fn > 0, f"{claim_id} has no true positives in the fixture -- recall is undefined"
    recall = tp / (tp + fn)
    assert recall >= _MIN_RECALL[claim_id], f"{claim_id} recall {recall:.2%} fell below floor"
