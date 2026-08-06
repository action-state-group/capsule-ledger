"""`capsule show` golden-output tests."""
from __future__ import annotations

import json
from pathlib import Path

from asg_ledger.cli.main import main

FIXTURE_LEDGER = Path(__file__).parent / "fixtures" / "sample_ledger.jsonl"
APPROVE_ID = "705955419ca6f944a75db77ae2a59844fdd99d355866c6c1dbc4ebe655c024c7"
REPORT_ID = "ac0d53a6fef41879e31faf20ae7f73b9d1facf07640c3c1ffc5ae4d8ab26d301"
CONFIRM_ID = "94c877c7ff0240cf7dafe2067f7016e5412d59b05f9eefa4baf90fc792f16142"


def test_show_by_prefix_renders_summary_and_echo(capsys):
    rc = main(["show", APPROVE_ID[:8], "--ledger", str(FIXTURE_LEDGER)])
    assert rc == 0
    out = capsys.readouterr().out
    assert f"capsule {APPROVE_ID}" in out
    assert "Agent:      procurement-agent@v1" in out
    assert "Verdict:    executed" in out
    assert "Chain:      (none)" in out
    assert "Constraints: (none)" in out
    assert out.rstrip().endswith(f"≡ capsule show {APPROVE_ID}")


def test_show_renders_constraints(capsys):
    rc = main(["show", REPORT_ID, "--ledger", str(FIXTURE_LEDGER)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Constraints:" in out
    assert "value_grounded: pass" in out
    assert "invoice_reconciles: pass" in out


def test_show_renders_chain_link(capsys):
    rc = main(["show", CONFIRM_ID, "--ledger", str(FIXTURE_LEDGER)])
    assert rc == 0
    out = capsys.readouterr().out
    assert f"Chain:      {APPROVE_ID} (confirms)" in out


def test_show_json_flag_prints_raw_capsule(capsys):
    rc = main(["show", APPROVE_ID, "--ledger", str(FIXTURE_LEDGER), "--json"])
    assert rc == 0
    capsule = json.loads(capsys.readouterr().out)
    assert capsule["capsule_id"] == APPROVE_ID


def test_show_not_found_is_a_clean_failure(capsys):
    rc = main(["show", "deadbeef", "--ledger", str(FIXTURE_LEDGER)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "no such capsule" in err
