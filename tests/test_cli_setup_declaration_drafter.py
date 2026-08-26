# SPDX-License-Identifier: Apache-2.0
"""``capsule setup propose --statement ... --outcome-id ... --drafter
{deepeval,static}`` CLI wiring ([ldg-english-to-declaration-drafter]):
extends the existing ``--drafter`` seam (``[ldg-propose-live-drafting-mode]``,
PR #67) from PROSE-only drafting to drafting the candidate DECLARATION
itself. ``--statement`` is opt-in and ``None`` by default, so the
pre-existing batch-propose path is unchanged when it is absent.
"""
from __future__ import annotations

import io

import yaml

from capsule_ledger.cli.main import main
from capsule_ledger.guards.signing import LocalSigner
from capsule_ledger.ledger import LedgerStore
from capsule_ledger.setup import declaration_drafter as setup_declaration_drafter
from capsule_ledger.setup.declarations import DeclarationStore
from capsule_ledger.setup.observe import ObserveRecorder


def _seed_ledger(ledger_dir) -> None:
    signer = LocalSigner(key_id="cli-key", secret=b"cli-secret")
    store = LedgerStore(ledger_dir)
    try:
        recorder = ObserveRecorder(
            ledger=store, signer=signer, operator="op", developer="dev", heartbeat_every=0, heartbeat_stream=io.StringIO()
        )
        events = []
        for i in range(1, 4):
            events.append({"kind": "dispatch", "dispatch_id": f"d{i}", "action_class": "remediation", "tool": "remediate"})
        events.append({"kind": "confirmation", "commitment_ref": "d1", "status": "confirmed"})
        recorder.run(events)
    finally:
        store.close()


def test_statement_without_outcome_id_is_a_usage_error(tmp_path, capsys):
    ledger_dir = tmp_path / "ledger"
    _seed_ledger(ledger_dir)
    rc = main(
        ["setup", "propose", "--project-dir", str(tmp_path), "--ledger", str(ledger_dir), "--statement", "a thing happened"]
    )
    assert rc == 1
    assert "--outcome-id is required" in capsys.readouterr().err


def test_statement_without_drafter_is_a_usage_error(tmp_path, capsys):
    ledger_dir = tmp_path / "ledger"
    _seed_ledger(ledger_dir)
    rc = main(
        [
            "setup", "propose",
            "--project-dir", str(tmp_path),
            "--ledger", str(ledger_dir),
            "--statement", "a thing happened",
            "--outcome-id", "outcome.x",
        ]
    )
    assert rc == 1
    assert "--drafter is required" in capsys.readouterr().err


def test_default_propose_never_constructs_declaration_drafter(tmp_path, monkeypatch):
    """RED-before-green guard: the batch (no --statement) path must never
    touch declaration_drafter at all -- a regression that imports/invokes it
    unconditionally fails this even without deepeval installed."""

    def _boom(self, *, model=None):
        raise AssertionError("DeepEvalDeclarationDrafter must never be constructed when --statement is absent")

    monkeypatch.setattr(setup_declaration_drafter.DeepEvalDeclarationDrafter, "__init__", _boom)
    ledger_dir = tmp_path / "ledger"
    _seed_ledger(ledger_dir)
    rc = main(["setup", "propose", "--project-dir", str(tmp_path), "--ledger", str(ledger_dir), "--drafter", "static"])
    assert rc == 0


def test_static_drafter_end_to_end_drafts_and_persists_a_declaration(tmp_path):
    ledger_dir = tmp_path / "ledger"
    _seed_ledger(ledger_dir)
    out = tmp_path / "proposals.yaml"

    rc = main(
        [
            "setup", "propose",
            "--project-dir", str(tmp_path),
            "--ledger", str(ledger_dir),
            "--statement", "a remediation action was confirmed by an external system (action_class:remediation)",
            "--outcome-id", "outcome.drafted_remediation",
            "--drafter", "static",
            "--out", str(out),
        ]
    )
    assert rc == 0

    data = yaml.safe_load(out.read_text())
    assert len(data["proposals"]) == 1
    proposal = data["proposals"][0]
    assert proposal["outcome_id"] == "outcome.drafted_remediation"
    assert proposal["forward_verdict"] == "DETERMINISTIC"
    assert proposal["backward_verdict"] == "DETERMINISTIC"
    assert proposal["coverage_n"] == 1
    assert proposal["coverage_m"] == 3
    assert proposal["drafted_by_model_id"] == "static-drafter/deterministic"
    assert "drafted_by_prompt_digest" in proposal
    assert proposal["declaration"]["params"]["action_class"] == "remediation"

    decl_store = DeclarationStore(tmp_path / ".capsule-setup")
    stored = decl_store.load("outcome.drafted_remediation")
    assert stored.acceptance_state == "proposed"
    assert stored.drafted_by_model_id == "static-drafter/deterministic"


def test_unmappable_statement_exits_nonzero_and_refuses(tmp_path, capsys):
    ledger_dir = tmp_path / "ledger"
    _seed_ledger(ledger_dir)

    rc = main(
        [
            "setup", "propose",
            "--project-dir", str(tmp_path),
            "--ledger", str(ledger_dir),
            "--statement", "the interaction increased the counterparty's trust in the system",
            "--outcome-id", "outcome.unmappable_cli",
            "--drafter", "static",
        ]
    )
    assert rc == 1
    out = capsys.readouterr().out
    assert "REFUSED" in out

    decl_store = DeclarationStore(tmp_path / ".capsule-setup")
    stored = decl_store.load("outcome.unmappable_cli")
    assert stored.refusal_reason_code == "statement_not_mappable"


def test_deepeval_declaration_drafter_missing_dependency_returns_1(tmp_path, capsys):
    if _deepeval_installed():
        import pytest

        pytest.skip("deepeval is installed in this environment -- the not-installed path isn't reachable here")
    ledger_dir = tmp_path / "ledger"
    _seed_ledger(ledger_dir)
    rc = main(
        [
            "setup", "propose",
            "--project-dir", str(tmp_path),
            "--ledger", str(ledger_dir),
            "--statement", "a thing happened",
            "--outcome-id", "outcome.x",
            "--drafter", "deepeval",
        ]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "drafter_dependency_missing" in err


def _deepeval_installed() -> bool:
    try:
        import deepeval  # noqa: F401
    except ImportError:
        return False
    return True
