"""`capsule agents --status` golden-output tests. The headline number is a real
fold evaluation (`actions.count_by_developer`), not a number this command
invents -- assert the literal DM Mono envelope line, not just a bare count."""
from __future__ import annotations

import re
from pathlib import Path

from asg_ledger.cli.main import main

FIXTURE_LEDGER = Path(__file__).parent / "fixtures" / "sample_ledger.jsonl"


def test_agents_status(capsys):
    rc = main(["agents", "--status", "--ledger", str(FIXTURE_LEDGER)])
    assert rc == 0
    out = capsys.readouterr().out

    assert out.startswith("≡ capsule agents --status\n")
    assert "procurement-agent@v1" in out
    assert "capturing:  yes · rung: self_attested" in out
    assert re.search(r"fold [0-9a-f]{64} · records 0–3 · checkpoint #4 · as of just now", out)
    assert "first seen: 2026-07-06T21:53:50.729284Z" in out
    assert "last seen:  2026-07-06T21:53:50.730668Z" in out
    assert "verdicts:   blocked:1 confirmed:1 executed:2" in out
    assert "see `capsule log --agent procurement-agent@v1`" in out
    assert "Coverage: 1 agent(s) captured in this ledger; no --enrolled list was given" in out
    assert "1 agent(s) · as of just now" in out
    assert "%" not in out


def test_agents_status_flag_required(capsys):
    rc = main(["agents", "--ledger", str(FIXTURE_LEDGER)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "only --status is implemented" in err


def test_agents_status_enrolled_not_capturing_shown_explicitly(capsys):
    rc = main(
        [
            "agents",
            "--status",
            "--ledger",
            str(FIXTURE_LEDGER),
            "--enrolled",
            "procurement-agent@v1,new-agent@v1",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out

    assert out.startswith("≡ capsule agents --status --enrolled procurement-agent@v1,new-agent@v1\n")
    # the captured agent still gets its full row
    assert "capturing:  yes · rung: self_attested" in out
    # the declared-but-never-seen agent is shown explicitly, not omitted
    assert "new-agent@v1\n  capturing:  no · declared via --enrolled, no records received yet" in out
    assert "Coverage: capturing from 1 of 2 declared agent(s); not yet capturing: new-agent@v1." in out
    assert "%" not in out


def test_agents_status_all_enrolled_agents_capturing(capsys):
    rc = main(
        ["agents", "--status", "--ledger", str(FIXTURE_LEDGER), "--enrolled", "procurement-agent@v1"]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "Coverage: capturing from 1 of 1 declared agent(s)." in out
    assert "not yet capturing" not in out
