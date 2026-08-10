# SPDX-License-Identifier: Apache-2.0
"""`capsule bisect` golden-output tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from capsule_ledger.cli.main import main
from capsule_ledger.ledger import LedgerStore

FIXTURES = Path(__file__).parent / "fixtures"
AMAURY = FIXTURES / "amaury_sample_ledger.jsonl"
NANDA = FIXTURES / "nanda_transaction_ledger.jsonl"

BLOCKED_ID = "cd0692b3349fadfeabe618008301b625059cc819eeb5ca1fb660699be9b6504e"  # seq 2, first blocked


def test_bisect_verdict_finds_first_matching_record(capsys):
    rc = main(["bisect", "--verdict", "blocked", "--ledger", str(AMAURY)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "first record where disposition.verdict_class == 'blocked':" in out
    assert f"capsule {BLOCKED_ID}" in out
    assert "seq:      #2 (of 4)" in out
    assert out.rstrip().endswith("≡ capsule bisect --verdict blocked")


def test_bisect_verdict_no_match_is_a_clean_failure(capsys):
    rc = main(["bisect", "--verdict", "nope", "--ledger", str(AMAURY)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "no record in this ledger satisfies: disposition.verdict_class == 'nope'" in err


def test_bisect_verdict_json_flag(capsys):
    rc = main(["bisect", "--verdict", "blocked", "--ledger", str(AMAURY), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["matched"] is True
    assert payload["record"]["capsule_id"] == BLOCKED_ID
    assert payload["record"]["seq"] == 2


def test_bisect_json_flag_no_match(capsys):
    rc = main(["bisect", "--verdict", "nope", "--ledger", str(AMAURY), "--json"])
    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["matched"] is False
    assert payload["record"] is None


def test_bisect_fold_threshold_finds_first_crossing(capsys):
    rc = main(
        [
            "bisect",
            "--fold", "actions.executed_count/1.0.0",
            "--key", "biz_capsule-0",
            "--gte", "20",
            "--ledger", str(NANDA),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "first record where actions.executed_count/1.0.0 gte 20:" in out
    assert "seq:      #20 (of 36)" in out


def test_bisect_fold_requires_a_threshold_op(capsys):
    rc = main(["bisect", "--fold", "actions.executed_count/1.0.0", "--ledger", str(NANDA)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "--fold requires one of --gt/--gte/--lt/--lte" in err


def test_bisect_unknown_fold_is_a_clean_failure(capsys):
    rc = main(["bisect", "--fold", "no.such.fold/9.9.9", "--gte", "1", "--ledger", str(AMAURY)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "no such fold" in err


def test_bisect_requires_verdict_or_fold(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["bisect", "--ledger", str(AMAURY)])
    assert exc_info.value.code == 2


def test_bisect_renders_gate_decision_fallback_for_absent_verdict_class(tmp_path, capsys):
    """An allow correctly omits verdict_class (guards/capsule.py) -- the
    display must render the gate decision it stands in for, never a bare
    "(none)" that reads as missing/broken data."""
    store = LedgerStore(tmp_path)
    allow_id = "9" * 64
    store.append(
        {
            "capsule_id": allow_id,
            "operator": "acme",
            "developer": "agent-1",
            "action_type": "approve_purchase",
            "timestamp": "2026-01-01T00:00:00Z",
            "disposition": {"decision": "accept", "verdict_class": None},
        },
        consequential=False,
    )
    store.close()

    rc = main(
        [
            "bisect",
            "--fold", "actions.count_by_developer/1.0.0",
            "--key", "agent-1",
            "--gte", "1",
            "--ledger", str(tmp_path),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "Verdict:  — (gate decision: accept; no effect claimed)" in out
    assert "Verdict:  (none)" not in out


def test_bisect_verdict_and_fold_are_mutually_exclusive(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["bisect", "--verdict", "blocked", "--fold", "x/1.0.0", "--ledger", str(AMAURY)])
    assert exc_info.value.code == 2
