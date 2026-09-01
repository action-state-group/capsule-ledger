# SPDX-License-Identifier: Apache-2.0
"""Arm A ("guards-only") vs Arm B ("full"): one codebase, one env var
(``CAPSULE_LEDGER_ARM``), never a fork -- see ``capsule_ledger/packaging.py``.

The report-rendering half of this arm mechanism (``render_report_html``'s
``arm`` chrome) lived here until the [ldg-ledger-scope-re-extraction]
RESIDUALS pass deleted ``report/`` -- see capsule-engine's
``tests/test_report_two_arm_rendering.py`` for that coverage now. This file
keeps only the CLI-registration half, which is core here.

Also the one place this repo checks, mechanically, that the private
thresholds doc's PASS/WORRY/FAIL numbers never made it into this repo: see
``test_no_threshold_bands_anywhere_in_telemetry_code`` at the bottom.
"""
from __future__ import annotations

from pathlib import Path

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
    # the constraints/fold/agents/telemetry surface stays available
    for verb in ("constraints", "fold", "agents", "telemetry"):
        assert verb in subs


@pytest.mark.parametrize("verb,extra", [("show", ["x"]), ("verify", ["x"]), ("bundle", []), ("log", [])])
def test_guards_only_arm_evidence_verbs_are_unregistered(guards_only_arm, verb, extra, capsys):
    with pytest.raises(SystemExit) as exc:
        cli_main([verb, *extra])
    assert exc.value.code == 2  # argparse's own "invalid choice" exit code
    err = capsys.readouterr().err
    assert "invalid choice" in err


# -- the hard boundary: no private threshold content in this repo -----------


def test_no_threshold_bands_anywhere_in_telemetry_code():
    """Mechanical guard, not a substitute for manual review: the telemetry
    code computes rates and nothing else -- no comparison against a
    pass/worry/fail band, no verdict, anywhere in this module tree. This
    intentionally does not encode any specific number from the private
    thresholds doc (that would defeat its own purpose); it only asserts
    that none of the *language* of grading a result appears."""
    import capsule_ledger.telemetry.funnel as funnel_mod

    src = Path(funnel_mod.__file__).read_text(encoding="utf-8")
    forbidden = ("pass_band", "worry_band", "fail_band", "verdict =", "grade(", "is_passing")
    for token in forbidden:
        assert token not in src
