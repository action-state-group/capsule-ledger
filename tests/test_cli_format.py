# SPDX-License-Identifier: Apache-2.0
"""``cli/format.py`` verdict-rendering helpers.

``disposition.verdict_class`` is legitimately absent for a gate decision
that never claims an execution outcome (an allow -- see
``guards/capsule.py``'s module docstring). The fallback must render the
``decision`` it stands in for, never a bare "(none)" that reads as
missing/broken data on a demo screen.
"""
from __future__ import annotations

from capsule_ledger.cli.format import format_verdict, format_verdict_label


def test_format_verdict_returns_verdict_class_when_present():
    assert format_verdict({"decision": "reject", "verdict_class": "blocked"}) == "blocked"


def test_format_verdict_falls_back_to_gate_decision_when_absent():
    assert (
        format_verdict({"decision": "accept", "verdict_class": None})
        == "— (gate decision: accept; no effect claimed)"
    )


def test_format_verdict_falls_back_when_verdict_class_key_missing():
    assert (
        format_verdict({"decision": "accept"}) == "— (gate decision: accept; no effect claimed)"
    )


def test_format_verdict_label_returns_verdict_class_when_present():
    assert format_verdict_label({"decision": "reject", "verdict_class": "blocked"}) == "blocked"


def test_format_verdict_label_falls_back_to_compact_gate_decision_when_absent():
    assert format_verdict_label({"decision": "accept", "verdict_class": None}) == "(gate decision: accept)"
