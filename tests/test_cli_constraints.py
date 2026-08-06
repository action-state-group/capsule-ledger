# SPDX-License-Identifier: Apache-2.0
"""`capsule constraints list` golden-output test: the registered guard checks
and the starter action-class taxonomy (no ledger needed -- code-derived)."""
from __future__ import annotations

from capsule_ledger.cli.main import main


def test_constraints_list(capsys):
    rc = main(["constraints", "list"])
    assert rc == 0
    out = capsys.readouterr().out

    assert "dedupe" in out
    assert "exact_match_index_v0" in out
    assert "caps" in out
    assert "spend.weekly/1.0.0" in out
    assert "verify_before_dispatch" in out
    assert "agent_action_capsule.verify" in out

    assert "money.transfer" in out
    assert "consequential=True" in out
    assert "info.query" in out
    assert "consequential=False" in out
    assert "fail_open_allowed=True" in out
    assert "unclassified" in out
