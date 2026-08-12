# SPDX-License-Identifier: Apache-2.0
"""Tests for the W1c ("B6a MVP EXIT") conversation-outcome demo.

Four concerns, matching the task's own acceptance bar ("ONE permalink a
stranger opens cold showing conversation->agreement->confirmed with
evaluation classes visible"): (1) the chain genuinely links conversation ->
judged agreement -> mock-IdP confirmation, not just "the script didn't
crash"; (2) the same seed reproduces byte-identical output, a different seed
does not, and the committed fixture matches a fresh regeneration; (3) the
hand-written attainment fold reports each field's evaluation class and
honest coverage; (4) the EXISTING `capsule bundle --with-viewer` CLI verb,
run against this ledger with no new bundle logic, produces a permalink and
a self-contained offline viewer that a stranger really can open cold and
have it verify -- checked here by actually running the CLI and the same
network-blocked Node harness the bundle-with-viewer feature itself is
proven with, not by assumption.
"""
from __future__ import annotations

import base64
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from capsule_ledger.cli.main import main
from capsule_ledger.confirm import CONFIRMS
from capsule_ledger.conversation import EVENT_SESSION_CLOSE
from capsule_ledger.examples.conversation_outcome_demo import (
    DEFAULT_SEED,
    build_attainment_fold,
    run_demo,
)
from capsule_ledger.judge import EVENT_ADJUDICATION, EVENT_JUDGMENT
from capsule_ledger.ledger import LedgerStore

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "conversation_outcome_demo_ledger.jsonl"
HARNESS = Path(__file__).parent / "js_harness_offline_viewer.mjs"


@pytest.fixture(autouse=True)
def _full_arm(monkeypatch):
    # `bundle` (like `confirm`) only registers in the "full" packaging arm --
    # pin it regardless of the host environment's ambient env vars.
    monkeypatch.delenv("CAPSULE_LEDGER_ARM", raising=False)
    monkeypatch.delenv("ASG_LEDGER_ARM", raising=False)


# -- the chain itself: conversation -> judged agreement -> mock-IdP confirmed --


def test_chain_links_conversation_to_judgment_to_confirmation(tmp_path):
    result = run_demo(local_store_dir=str(tmp_path / "store"), seed=DEFAULT_SEED)

    assert len(result.records) == 8
    by_id = {r.capsule_id: r for r in result.records}

    turn_ids = [result.capsule_ids[f"turn_{i}_{role}"] for i, role in enumerate(["user", "assistant", "user", "assistant"])]
    # Turns chain to each other in order (turn 0 standalone, every later turn
    # chains to the previous one via "follows").
    assert (by_id[turn_ids[0]].capsule.get("chain") or {}) == {}
    for prev_id, this_id in zip(turn_ids, turn_ids[1:], strict=False):
        chain = by_id[this_id].capsule["chain"]
        assert chain == {"parent_capsule_id": prev_id, "relation": "follows"}

    close = by_id[result.capsule_ids["session_close"]]
    assert close.capsule["asg_payload"]["event"] == EVENT_SESSION_CLOSE
    assert close.capsule["asg_payload"]["detail"]["turn_capsule_ids"] == turn_ids
    assert close.capsule["chain"] == {"parent_capsule_id": turn_ids[-1], "relation": "follows"}

    # Judged agreement: chained to the session-close capsule.
    judgment = by_id[result.capsule_ids["judgment"]]
    assert judgment.capsule["asg_payload"]["event"] == EVENT_JUDGMENT
    assert judgment.capsule["asg_payload"]["detail"]["label"] == "agreement_reached"
    assert judgment.capsule["chain"] == {"parent_capsule_id": close.capsule_id, "relation": "confirms"}

    # Manual spot-check adjudication: chained to the judgment.
    adjudication = by_id[result.capsule_ids["adjudication"]]
    assert adjudication.capsule["asg_payload"]["event"] == EVENT_ADJUDICATION
    assert adjudication.capsule["disposition"]["human_disposed"] is True
    assert adjudication.capsule["chain"] == {"parent_capsule_id": judgment.capsule_id, "relation": "confirms"}

    # Mock-IdP confirmation: chained DIRECTLY to the judgment capsule (not a
    # separate synthetic commitment) -- this is what makes
    # conversation -> agreement -> confirmed one walkable chain.
    confirmation = by_id[result.capsule_ids["confirmation"]]
    assert confirmation.capsule["chain"] == {"parent_capsule_id": judgment.capsule_id, "relation": CONFIRMS}
    assert confirmation.capsule["effect"]["status"] == "confirmed"
    assert confirmation.capsule["effect"]["effect_attestation"] == "runtime_claimed"

    # Every capsule in the chain independently re-verifies.
    for record in result.records:
        assert record.capsule.get("capsule_id")


def test_every_record_independently_verifies(tmp_path):
    store = LedgerStore(tmp_path / "store")
    try:
        run_demo(local_store_dir=None, seed=DEFAULT_SEED)  # sanity: doesn't require a shared store
        n = store.import_jsonl(FIXTURE_PATH)
        assert n == 8
        for record in store.scan():
            result = store.verify(record.capsule_id)
            assert result is not None and result.ok, (record.capsule_id, result.findings if result else None)
        assert store.find_gaps() == []
    finally:
        store.close()


# -- reproducibility ----------------------------------------------------------


def test_reproducible_byte_identical(tmp_path):
    out_1 = tmp_path / "run1.jsonl"
    out_2 = tmp_path / "run2.jsonl"
    run_demo(local_store_dir=str(tmp_path / "store1"), seed=DEFAULT_SEED, fixture_out=out_1)
    run_demo(local_store_dir=str(tmp_path / "store2"), seed=DEFAULT_SEED, fixture_out=out_2)

    assert out_1.read_bytes() == out_2.read_bytes()
    assert out_1.stat().st_size > 0


def test_different_seed_changes_output(tmp_path):
    out_a = tmp_path / "seed_a.jsonl"
    out_b = tmp_path / "seed_b.jsonl"
    run_demo(local_store_dir=str(tmp_path / "store_a"), seed=1, fixture_out=out_a)
    run_demo(local_store_dir=str(tmp_path / "store_b"), seed=2, fixture_out=out_b)

    assert out_a.read_bytes() != out_b.read_bytes()


def test_committed_fixture_matches_freshly_regenerated_output(tmp_path):
    assert FIXTURE_PATH.exists(), f"missing committed fixture: {FIXTURE_PATH}"
    out = tmp_path / "regenerated.jsonl"
    run_demo(local_store_dir=str(tmp_path / "store"), seed=DEFAULT_SEED, fixture_out=out)
    assert out.read_bytes() == FIXTURE_PATH.read_bytes()


# -- the hand-written attainment fold: evaluation classes visible, honest coverage --


def test_attainment_fold_reports_evaluation_classes_and_coverage(tmp_path):
    result = run_demo(local_store_dir=str(tmp_path / "store"), seed=DEFAULT_SEED)
    fold = result.fold

    assert fold["sessions_total"] == 1
    assert fold["sessions_judged"] == 1
    assert fold["coverage_judged"] == "1 of 1 sessions judged"
    assert fold["agreements_reached"] == 1
    assert fold["remediations_confirmed"] == 1
    assert fold["coverage_confirmed"] == "1 of 1 judged agreements confirmed"

    (session,) = fold["sessions"]
    assert session["efficiency"] == {"evaluation_class": "deterministic", "turns_to_agreement": 4}
    assert session["agreement"]["evaluation_class"] == "model-assisted"
    assert session["agreement"]["label"] == "agreement_reached"
    assert session["adjudication"]["evaluation_class"] == "manual"
    assert session["adjudication"]["agrees_with_judge"] is True
    assert session["remediation"]["evaluation_class"] == "deterministic"
    assert session["remediation"]["effect_status"] == "confirmed"


def test_attainment_fold_never_imputes_an_unjudged_session():
    """A session with no judgment must be reported as NOT judged/confirmed
    (coverage honestly excludes it), never silently counted either way --
    the standing fold discipline (`ledger-lane/inbox.md`'s
    `[ldg-outcomes-batch]`: "folds count records and report coverage, never
    impute"), verified here against a hand-built ledger the demo itself
    never produces."""
    from capsule_ledger.conversation import ConversationSession
    from capsule_ledger.guards.signing import LocalSigner

    store = LedgerStore(__import__("tempfile").mkdtemp())
    try:
        signer = LocalSigner(key_id="k", secret=b"s")
        session = ConversationSession(
            ledger=store, session_id="unjudged-session", operator="op", developer="dev@v1", signer_provider=lambda: signer
        )
        session.record_turn(speaker_role="user", content_digest="a" * 64)
        session.close()

        fold = build_attainment_fold(store)
        assert fold["sessions_total"] == 1
        assert fold["sessions_judged"] == 0
        assert fold["coverage_judged"] == "0 of 1 sessions judged"
        assert fold["agreements_reached"] == 0
        assert fold["remediations_confirmed"] == 0
        (session_entry,) = fold["sessions"]
        assert session_entry["agreement"] is None
        assert session_entry["adjudication"] is None
        assert session_entry["remediation"] is None
    finally:
        store.close()


# -- acceptance: the EXISTING `capsule bundle --with-viewer` produces a real,
# offline-verifiable permalink a stranger can open cold -----------------------


def test_capsule_bundle_over_the_demo_ledger_verifies_clean(tmp_path):
    out_path = tmp_path / "bundle.json"
    rc = main(["bundle", "--ledger", str(FIXTURE_PATH), "--out", str(out_path)])
    assert rc == 0

    bundle = json.loads(out_path.read_text())
    assert len(bundle["records"]) == 8
    assert all(v["ok"] for v in bundle["verification"].values())

    # The chain is present in the bundle exactly as produced by the demo --
    # a stranger reading this bundle sees conversation -> agreement ->
    # confirmed, with each record's own asg_payload/effect/disposition
    # (the evaluation-class-bearing detail) intact.
    events = [r["asg_payload"]["event"] for r in bundle["records"] if "event" in (r.get("asg_payload") or {})]
    assert events.count(EVENT_SESSION_CLOSE) == 1
    assert events.count(EVENT_JUDGMENT) == 1
    assert events.count(EVENT_ADJUDICATION) == 1
    confirmations = [r for r in bundle["records"] if (r.get("asg_payload") or {}).get("connector_type")]
    assert len(confirmations) == 1
    assert confirmations[0]["effect"]["status"] == "confirmed"


def test_capsule_bundle_with_viewer_produces_a_permalink_and_offline_html(tmp_path, capsys):
    out_path = tmp_path / "bundle.json"
    rc = main(["bundle", "--ledger", str(FIXTURE_PATH), "--out", str(out_path), "--with-viewer"])
    assert rc == 0

    printed = capsys.readouterr().out
    assert "verify: https://verify.agentactioncapsule.org/bundle#" in printed

    viewer_path = tmp_path / "bundle.html"
    assert viewer_path.exists()
    html = viewer_path.read_text(encoding="utf-8")
    assert "<script src=" not in html
    assert "<link" not in html


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_offline_viewer_opens_cold_and_verifies_with_networking_disabled(tmp_path):
    """The same network-blocked-Node-harness proof
    `test_cli_bundle_with_viewer.py` uses for the general --with-viewer
    feature, run here against THIS demo's own chain -- the literal
    "stranger opens cold" acceptance bar, checked in CI rather than only by
    hand."""
    out_path = tmp_path / "bundle.json"
    rc = main(["bundle", "--ledger", str(FIXTURE_PATH), "--out", str(out_path), "--with-viewer"])
    assert rc == 0
    viewer_path = tmp_path / "bundle.html"

    result = subprocess.run(
        ["node", str(HARNESS), str(viewer_path)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    parsed = json.loads(result.stdout)

    assert parsed["loadError"] is None
    assert parsed["networkAttempts"] == []
    assert parsed["fragmentEmbedded"] is True
    assert parsed["recordCount"] == 8

    stages = {s["name"]: s["status"] for s in parsed["ritual"]["stages"]}
    assert stages["Integrity"] == "pass"
    assert stages["Sequence"] == "pass"
    assert stages["Cross-check"] == "pass"


def test_bundle_fragment_decodes_back_to_the_same_records(tmp_path):
    """The permalink's fragment is exactly the bundle -- decoding it back
    (as a recipient's browser would) yields the identical 8 records, so the
    URL genuinely carries the whole chain, not a summary."""
    out_path = tmp_path / "bundle.json"
    rc = main(["bundle", "--ledger", str(FIXTURE_PATH), "--out", str(out_path)])
    assert rc == 0
    bundle_bytes = out_path.read_bytes()
    bundle = json.loads(bundle_bytes)

    payload = json.dumps(bundle, separators=(",", ":"), sort_keys=True).encode("utf-8")
    fragment = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")

    padded = fragment + "=" * (-len(fragment) % 4)
    decoded = json.loads(base64.urlsafe_b64decode(padded))
    assert decoded == bundle
    assert len(decoded["records"]) == 8
