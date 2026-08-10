# SPDX-License-Identifier: Apache-2.0
"""`capsule diff` golden-output tests.

Epoch-diff acceptance (per the task): a meaningful before/after diff on the
tax-audit-style fixture (`nanda_transaction_ledger.jsonl`) -- see
`test_nanda_before_after_diff_is_meaningful` below.
"""
from __future__ import annotations

import json
from pathlib import Path

from capsule_ledger.cli.main import main
from capsule_ledger.ledger import LedgerStore

FIXTURES = Path(__file__).parent / "fixtures"
AMAURY = FIXTURES / "amaury_sample_ledger.jsonl"
NANDA = FIXTURES / "nanda_transaction_ledger.jsonl"

APPROVE_ID = "705955419ca6f944a75db77ae2a59844fdd99d355866c6c1dbc4ebe655c024c7"  # seq 1, executed
BLOCKED_ID = "cd0692b3349fadfeabe618008301b625059cc819eeb5ca1fb660699be9b6504e"  # seq 2, blocked
REPORT_ID = "ac0d53a6fef41879e31faf20ae7f73b9d1facf07640c3c1ffc5ae4d8ab26d301"  # seq 3, executed
CONFIRM_ID = "94c877c7ff0240cf7dafe2067f7016e5412d59b05f9eefa4baf90fc792f16142"  # seq 4, confirmed


def test_diff_by_seq_refs_shows_added_records_and_verdict_delta(capsys):
    rc = main(["diff", "1", "3", "--ledger", str(AMAURY)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "checkpoint #1 (1) → checkpoint #3 (3)" in out
    assert "2 new record(s):" in out
    assert BLOCKED_ID[:16] in out
    assert REPORT_ID[:16] in out
    assert APPROVE_ID[:16] not in out.split("2 new record(s):")[1]
    assert "verdict distribution delta:" in out
    assert "blocked: 0 → 1 (+1)" in out
    assert "executed: 1 → 2 (+1)" in out
    assert out.rstrip().endswith("≡ capsule diff 1 3")


def test_diff_to_ref_defaults_to_head(capsys):
    rc = main(["diff", "0", "--ledger", str(AMAURY)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "checkpoint #0 (0) → checkpoint #4 (HEAD)" in out
    assert "4 new record(s):" in out


def test_diff_capsule_id_ref_resolves_to_its_seq(capsys):
    rc = main(["diff", APPROVE_ID, "HEAD", "--ledger", str(AMAURY)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "checkpoint #1" in out
    assert "3 new record(s):" in out


def test_diff_timestamp_ref(capsys):
    rc = main(["diff", "2026-07-06T21:53:50.730086Z", "HEAD", "--ledger", str(AMAURY)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "checkpoint #2" in out


def test_diff_unresolvable_ref_is_a_clean_failure(capsys):
    rc = main(["diff", "not-a-real-ref", "HEAD", "--ledger", str(AMAURY)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "cannot resolve ref" in err


def test_diff_same_checkpoint_reports_no_changes(capsys):
    rc = main(["diff", "2", "2", "--ledger", str(AMAURY)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "no new or removed records between these checkpoints" in out
    assert "verdict distribution: unchanged" in out


def test_diff_json_flag(capsys):
    rc = main(["diff", "1", "3", "--ledger", str(AMAURY), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["from"] == {"ref": "1", "checkpoint": 1}
    assert payload["to"] == {"ref": "3", "checkpoint": 3}
    assert set(payload["added"]) == {BLOCKED_ID, REPORT_ID}
    assert payload["removed"] == []
    assert payload["verdict_delta"]["blocked"] == {"from": 0, "to": 1}


def test_diff_renders_gate_decision_fallback_for_absent_verdict_class(tmp_path, capsys):
    """An allow correctly omits verdict_class (guards/capsule.py) -- the
    added-record row and the verdict-distribution delta must render the
    gate decision it stands in for, never a bare "(none)" that reads as
    missing/broken data."""
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

    rc = main(["diff", "0", "HEAD", "--ledger", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert allow_id[:16] in out
    assert "(gate decision: accept)" in out
    assert "(none)" not in out


def test_diff_fold_delta(capsys):
    rc = main(
        [
            "diff", "18", "HEAD",
            "--ledger", str(NANDA),
            "--fold", "actions.executed_count/1.0.0",
            "--key", "biz_capsule-0",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "fold deltas:" in out
    assert "actions.executed_count/1.0.0: 18 → 36" in out


def test_diff_unknown_fold_is_a_clean_failure(capsys):
    rc = main(["diff", "1", "HEAD", "--ledger", str(AMAURY), "--fold", "no.such.fold/9.9.9"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "no such fold" in err


def test_nanda_before_after_diff_is_meaningful(capsys):
    """Acceptance test: a before/after diff on the tax-audit-style fixture
    must render a meaningful (non-empty, non-trivial) diff."""
    rc = main(["diff", "18", "HEAD", "--ledger", str(NANDA)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "18 new record(s):" in out
    assert "executed: 18 → 36 (+18)" in out
    # every added record's capsule_id actually appears, not just a count
    added_lines = [line for line in out.splitlines() if line.strip().startswith("+ capsule")]
    assert len(added_lines) == 18
