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
    assert re.search(r"fold [0-9a-f]{64} · records 0–3 · checkpoint #4 · as of just now", out)
    assert "first seen: 2026-07-06T21:53:50.729284Z" in out
    assert "last seen:  2026-07-06T21:53:50.730668Z" in out
    assert "verdicts:   blocked:1 confirmed:1 executed:2" in out
    assert "see `capsule log --agent procurement-agent@v1`" in out
    assert "1 agent(s) · as of just now" in out


def test_agents_status_flag_required(capsys):
    rc = main(["agents", "--ledger", str(FIXTURE_LEDGER)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "only --status is implemented" in err
