# SPDX-License-Identifier: Apache-2.0
"""Arm A ("guards-only") vs Arm B ("full"): one codebase, one env var
(``CAPSULE_LEDGER_ARM``), never a fork -- see ``capsule_ledger/packaging.py``.

The report-rendering half of this arm mechanism (``render_report_html``'s
``arm`` chrome) lived here until the [ldg-ledger-scope-re-extraction]
RESIDUALS pass deleted ``report/`` -- see capsule-engine's
``tests/test_report_two_arm_rendering.py`` for that coverage now. This file
keeps only the CLI-registration half, which is core here.
"""
from __future__ import annotations

import pytest

from capsule_ledger.cli.main import _build_parser
from capsule_ledger.cli.main import main as cli_main


@pytest.fixture
def guards_only_arm(monkeypatch):
    monkeypatch.setenv("CAPSULE_LEDGER_ARM", "guards-only")


# -- command registration ---------------------------------------------------


def _subcommands(arm: str) -> set[str]:
    parser = _build_parser(arm)
    sub_action = next(a for a in parser._subparsers._group_actions if a.choices is not None)
    return set(sub_action.choices)


def test_full_arm_registers_evidence_verbs():
    subs = _subcommands("full")
    for verb in ("log", "show", "verify", "bundle"):
        assert verb in subs


def test_guards_only_arm_hides_evidence_verbs():
    subs = _subcommands("guards-only")
    for verb in ("log", "show", "verify", "bundle"):
        assert verb not in subs
    # the constraints/fold/agents surface stays available
    for verb in ("constraints", "fold", "agents"):
        assert verb in subs


@pytest.mark.parametrize("verb,extra", [("show", ["x"]), ("verify", ["x"]), ("bundle", []), ("log", [])])
def test_guards_only_arm_evidence_verbs_are_unregistered(guards_only_arm, verb, extra, capsys):
    with pytest.raises(SystemExit) as exc:
        cli_main([verb, *extra])
    assert exc.value.code == 2  # argparse's own "invalid choice" exit code
    err = capsys.readouterr().err
    assert "invalid choice" in err
