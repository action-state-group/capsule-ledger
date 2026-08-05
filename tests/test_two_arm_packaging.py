# SPDX-License-Identifier: Apache-2.0
"""Arm A ("guards-only") vs Arm B ("full"): one codebase, one env var
(``ASG_LEDGER_ARM``), never a fork -- see ``asg_ledger/packaging.py``.

Also the one place this repo checks, mechanically, that the private
thresholds doc's PASS/WORRY/FAIL numbers never made it into this repo: see
``test_no_threshold_bands_anywhere_in_telemetry_code`` at the bottom.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from asg_ledger.cli.main import _build_parser
from asg_ledger.cli.main import main as cli_main
from asg_ledger.report import build_dry_run_report, render_report_html

FIXTURES = Path(__file__).parent / "fixtures"
NANDA = FIXTURES / "nanda_transaction_ledger.jsonl"


@pytest.fixture
def full_arm(monkeypatch):
    monkeypatch.delenv("ASG_LEDGER_ARM", raising=False)


@pytest.fixture
def guards_only_arm(monkeypatch):
    monkeypatch.setenv("ASG_LEDGER_ARM", "guards-only")


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
    # the guard/constraints/fold/agents/telemetry surface stays available
    for verb in ("guard", "constraints", "fold", "agents", "telemetry"):
        assert verb in subs


@pytest.mark.parametrize("verb,extra", [("show", ["x"]), ("verify", ["x"]), ("bundle", []), ("log", [])])
def test_guards_only_arm_evidence_verbs_are_unregistered(guards_only_arm, verb, extra, capsys):
    with pytest.raises(SystemExit) as exc:
        cli_main([verb, *extra])
    assert exc.value.code == 2  # argparse's own "invalid choice" exit code
    err = capsys.readouterr().err
    assert "invalid choice" in err


# -- guard dry-run CLI output -------------------------------------------------


def test_full_arm_share_prints_the_permalink(full_arm, tmp_path, capsys):
    out = tmp_path / "report.html"
    rc = cli_main(["guard", "dry-run", "--ledger", str(NANDA), "--since", "7d", "--out", str(out), "--share"])
    assert rc == 0
    printed = capsys.readouterr().out
    assert f"file://{out.resolve()}#" in printed


def test_guards_only_arm_share_prints_no_permalink(guards_only_arm, tmp_path, capsys):
    out = tmp_path / "report.html"
    rc = cli_main(["guard", "dry-run", "--ledger", str(NANDA), "--since", "7d", "--out", str(out), "--share"])
    assert rc == 0
    printed = capsys.readouterr().out
    assert "file://" not in printed
    assert out.exists()  # the report itself is still written


def test_full_arm_verify_wording_mentions_capsule(full_arm, tmp_path, capsys):
    out = tmp_path / "report.html"
    rc = cli_main(["guard", "dry-run", "--ledger", str(NANDA), "--since", "7d", "--out", str(out), "--verify"])
    assert rc == 0
    assert "capsule" in capsys.readouterr().out


def test_guards_only_arm_verify_wording_never_mentions_capsule(guards_only_arm, tmp_path, capsys):
    out = tmp_path / "report.html"
    rc = cli_main(["guard", "dry-run", "--ledger", str(NANDA), "--since", "7d", "--out", str(out), "--verify"])
    assert rc == 0
    printed = capsys.readouterr().out
    assert "capsule" not in printed.lower()
    assert "OK: report is reproducible" in printed


def test_guard_enforce_records_locally_without_pretending_to_gate(guards_only_arm, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("ASG_LEDGER_STATE_DIR", str(tmp_path))
    rc = cli_main(["guard", "enforce"])
    assert rc == 0
    assert "does not itself gate actions" in capsys.readouterr().out


# -- report rendering ---------------------------------------------------------


def test_render_report_html_default_arm_is_full(caps_fold):
    report = build_dry_run_report([str(NANDA)], caps_fold=caps_fold, since="7d")
    html, _ = render_report_html(report)
    assert 'data-arm="full"' in html
    assert '[data-arm="guards-only"]' not in html


def test_render_report_html_guards_only_hides_evidence_chrome(caps_fold):
    report = build_dry_run_report([str(NANDA)], caps_fold=caps_fold, since="7d")
    html, _ = render_report_html(report, arm="guards-only")
    assert 'data-arm="guards-only"' in html
    assert '[data-arm="guards-only"] .share-row' in html
    assert '[data-arm="guards-only"] .row-fp' in html


def test_render_report_html_verify_js_is_byte_identical_across_arms(caps_fold):
    """The evidence-hiding mechanism must never touch verify.js itself --
    only the surrounding static shell -- so the JS/Python digest-parity
    tests in test_report_dry_run.py keep meaning what they say in both arms."""
    report = build_dry_run_report([str(NANDA)], caps_fold=caps_fold, since="7d")
    full_html, _ = render_report_html(report, arm="full")
    guards_html, _ = render_report_html(report, arm="guards-only")

    def _script_body(html: str) -> str:
        start = html.index("<script>\n") + len("<script>\n")
        end = html.index("</script>", start)
        return html[start:end]

    assert _script_body(full_html) == _script_body(guards_html)


# -- the hard boundary: no private threshold content in this repo -----------


def test_no_threshold_bands_anywhere_in_telemetry_code():
    """Mechanical guard, not a substitute for manual review: the telemetry
    code computes rates and nothing else -- no comparison against a
    pass/worry/fail band, no verdict, anywhere in this module tree. This
    intentionally does not encode any specific number from the private
    thresholds doc (that would defeat its own purpose); it only asserts
    that none of the *language* of grading a result appears."""
    import asg_ledger.telemetry.funnel as funnel_mod

    src = Path(funnel_mod.__file__).read_text(encoding="utf-8")
    forbidden = ("pass_band", "worry_band", "fail_band", "verdict =", "grade(", "is_passing")
    for token in forbidden:
        assert token not in src
