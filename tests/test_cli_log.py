# SPDX-License-Identifier: Apache-2.0
"""`capsule log` golden-output tests."""
from __future__ import annotations

import json
from pathlib import Path

from capsule_ledger.cli.main import main
from capsule_ledger.ledger import LedgerStore

FIXTURE_LEDGER = Path(__file__).parent / "fixtures" / "sample_ledger.jsonl"


def test_log_no_filters_lists_all_records(capsys):
    rc = main(["log", "--ledger", str(FIXTURE_LEDGER)])
    assert rc == 0
    out = capsys.readouterr().out
    assert out.startswith("≡ capsule log\n")
    assert "capsule 705955419ca6f944a75db77ae2a59844fdd99d355866c6c1dbc4ebe655c024c7" in out
    assert "approve_purchase" in out
    assert "transfer_funds" in out
    assert "generate_report" in out
    assert "confirm_purchase" in out
    assert (
        "4 of 4 records shown (filtered view — the ledger itself is never filtered) "
        "· sequence unbroken · as of just now" in out
    )


def test_log_filter_by_verdict(capsys):
    rc = main(["log", "--ledger", str(FIXTURE_LEDGER), "--verdict", "blocked"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "≡ capsule log --verdict blocked" in out
    assert "transfer_funds" in out
    assert "approve_purchase" not in out
    assert "1 of 4 records shown" in out


def test_log_filter_by_agent_and_action_type_builds_canonical_echo(capsys):
    rc = main(
        [
            "log",
            "--ledger",
            str(FIXTURE_LEDGER),
            "--action-type",
            "decide",
            "--agent",
            "procurement-agent@v1",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    # Canonical (fixed) flag order regardless of the order given on argv.
    assert "≡ capsule log --agent procurement-agent@v1 --action-type decide" in out
    assert "4 of 4 records shown" in out


def test_log_no_ledger_given_errors(capsys, monkeypatch):
    monkeypatch.delenv("CAPSULE_LEDGER", raising=False)
    monkeypatch.delenv("ASG_LEDGER", raising=False)
    rc = main(["log"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "--ledger is required" in err


def test_log_capsule_ledger_env_var_used_when_no_ledger_flag(capsys, monkeypatch):
    """CAPSULE_LEDGER set, no --ledger flag, no ASG_LEDGER -> new env var used."""
    monkeypatch.delenv("ASG_LEDGER", raising=False)
    monkeypatch.setenv("CAPSULE_LEDGER", str(FIXTURE_LEDGER))
    rc = main(["log"])
    assert rc == 0
    assert "approve_purchase" in capsys.readouterr().out


def test_log_legacy_asg_ledger_env_var_still_works_as_fallback(capsys, monkeypatch):
    """CAPSULE_LEDGER unset, ASG_LEDGER set -> old value used as fallback."""
    monkeypatch.delenv("CAPSULE_LEDGER", raising=False)
    monkeypatch.setenv("ASG_LEDGER", str(FIXTURE_LEDGER))
    rc = main(["log"])
    assert rc == 0
    assert "approve_purchase" in capsys.readouterr().out


def test_log_renders_gate_decision_fallback_for_absent_verdict_class(tmp_path, capsys):
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

    rc = main(["log", "--ledger", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Verdict:  — (gate decision: accept; no effect claimed)" in out
    assert "Verdict:  (none)" not in out


def test_log_reports_a_chain_gap_instead_of_falsely_claiming_unbroken(tmp_path, capsys):
    capsules = [json.loads(line) for line in FIXTURE_LEDGER.read_text().splitlines() if line.strip()]
    tampered = dict(capsules[1])
    tampered["chain"] = {"parent_capsule_id": "no-such-parent-in-this-ledger", "relation": "confirms"}
    gapped_ledger = tmp_path / "gapped.jsonl"
    with open(gapped_ledger, "w") as fh:
        for c in [capsules[0], tampered]:
            fh.write(json.dumps(c) + "\n")

    rc = main(["log", "--ledger", str(gapped_ledger)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "sequence unbroken" not in out
    assert "1 chain gap(s) detected" in out
