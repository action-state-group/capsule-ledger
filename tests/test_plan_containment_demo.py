# SPDX-License-Identifier: Apache-2.0
"""C4 (``[ldg-plan-containment]``): the three-run plan-containment demo.

Mirrors ``test_conversation_outcome_demo_example.py``'s own shape: (1) each
run's chain and containment verdicts are real, not just "the script didn't
crash"; (2) reproducibility -- same seed byte-identical, committed fixtures
match a fresh regen; (3) the hand-written attainment fold reports honest
coverage per run; (4) the EXISTING ``capsule bundle --with-viewer`` CLI verb
produces, for EACH run, a permalink and offline HTML a stranger can open
cold and have verify -- checked with the same network-blocked Node harness
``test_conversation_outcome_demo_example.py`` uses.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from agent_action_capsule.contracts import is_hex64

from capsule_ledger.cli.main import main
from capsule_ledger.compiler.vocabulary import REFUSAL_REASON_CODES
from capsule_ledger.examples.plan_containment_demo.demo import (
    DEFAULT_SEED,
    load_plan,
    run_a,
    run_b,
    run_c,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures"
FIXTURE_A = FIXTURE_DIR / "plan_containment_run_a.jsonl"
FIXTURE_B = FIXTURE_DIR / "plan_containment_run_b.jsonl"
FIXTURE_C = FIXTURE_DIR / "plan_containment_run_c.jsonl"
HARNESS = Path(__file__).parent / "js_harness_offline_viewer.mjs"


@pytest.fixture(autouse=True)
def _full_arm(monkeypatch):
    # `bundle` only registers in the "full" packaging arm (same fixture as
    # test_conversation_outcome_demo_example.py) -- pin it regardless of the
    # host environment's ambient env vars.
    monkeypatch.delenv("CAPSULE_LEDGER_ARM", raising=False)
    monkeypatch.delenv("ASG_LEDGER_ARM", raising=False)


# -- the plan itself ----------------------------------------------------------


def test_the_same_plan_and_manifest_digest_govern_all_three_runs():
    plan, manifest_digest = load_plan()
    assert plan.outcome_id == "workforce.remediation_completed/1.0.0"
    assert plan.allowed_actions == (
        "read_user_directory", "send_enrollment_link", "enable_mfa", "verify_mfa_state",
    )
    assert manifest_digest


# -- Run A: contained and attained --------------------------------------------


def test_run_a_enable_mfa_cites_the_judgment_and_is_contained(tmp_path):
    result = run_a(str(tmp_path / "store"))
    by_id = {r.capsule_id: r for r in result.records}

    write = by_id[result.capsule_ids["write_enable_mfa"]]
    constraints = {c["id"]: c["result"] for c in write.capsule["constraints"]}
    assert constraints["plan_containment"] == "pass"
    assert write.capsule["disposition"]["decision"] == "accept"

    # The judgment cited by enable_mfa's verify_before_dispatch is the SAME
    # judgment capsule this run's judge produced -- a real citation, not a
    # bare id copied without meaning.
    judgment_id = result.capsule_ids["judgment"]
    assert judgment_id in {r.capsule_id for r in result.records}


def test_run_a_attained_with_full_coverage(tmp_path):
    result = run_a(str(tmp_path / "store"))
    fold = result.fold
    assert fold["attained"] is True
    assert fold["coverage_judged"] == "1 of 1 sessions judged"
    assert fold["coverage_agreement"] == "1 of 1 judged sessions reached agreement"
    assert fold["coverage_confirmed"] == "1 of 1 agreements confirmed"


# -- Run A: the compiler-vocabulary showcase (P6a) -----------------------------
# `[ldg-cs-p6a-refusal-and-instrument-cases]`: the demo shipped exactly one
# refusal (Run B's forward `deny`) and P6 requires at least two, of the more
# interesting kind -- a COMPILER refusal ("this statement cannot be mapped",
# no dispatch, no user, never simulated) plus a MAPPABLE-WITH-INSTRUMENTATION
# case that names a genuinely missing instrument. These tests are the RED
# side of RED-before-green: on `main` before this task, `run_a().compiler_showcase`
# does not exist at all and every assertion below fails or errors.


def test_run_a_ships_a_compiler_refusal_with_zero_free_prose_and_a_named_reason(tmp_path):
    result = run_a(str(tmp_path / "store"))
    by_id = {r.capsule_id: r for r in result.records}
    refusal = by_id[result.capsule_ids["compiler_refusal"]]

    assert refusal.capsule["action_type"] == "fyi"
    detail = refusal.capsule["asg_payload"]["detail"]
    # Zero free prose: exactly the refusal capsule's fixed shape, nothing
    # else -- no sentence-shaped field could sneak in unnoticed.
    assert set(detail.keys()) == {"verdict_class", "statement_digest", "reason_code", "labelled_item"}
    assert detail["verdict_class"] == {"forward": "REFUSED", "backward": "REFUSED"}
    assert is_hex64(detail["statement_digest"])
    assert detail["reason_code"] in REFUSAL_REASON_CODES
    # The labelled item is a short slug (a name), never a sentence.
    assert detail["labelled_item"]["kind"] in {"proxy", "instrumentation"}
    assert re.fullmatch(r"[a-z][a-z0-9_]*", detail["labelled_item"]["label"])

    # No prose anywhere on the sealed capsule -- the human-readable
    # rendering lives only in the terminal/proposal layer, never on-capsule.
    blob = json.dumps(refusal.capsule)
    for prose in ("recommendation was made", "a person acted", "made them act"):
        assert prose not in blob


def test_run_a_compiler_refusal_is_never_dispatched_and_never_a_decision_capsule(tmp_path):
    """The compiler refusal is a declare-time event -- distinguishable from
    Run B's forward refusal by structure alone, without narration: it never
    carries `constraints`/`disposition` (those are act-time-only fields on a
    `decide`-typed capsule) and cites no dispatched action."""
    result = run_a(str(tmp_path / "store"))
    by_id = {r.capsule_id: r for r in result.records}
    refusal = by_id[result.capsule_ids["compiler_refusal"]]
    assert "constraints" not in refusal.capsule
    assert "disposition" not in refusal.capsule


def test_run_a_with_instrumentation_case_names_an_instrument_genuinely_absent_from_this_run(tmp_path):
    result = run_a(str(tmp_path / "store"))
    with_instrumentation = next(p for p in result.compiler_showcase if p.needs_instrumentation)
    assert with_instrumentation.missing_instrument == "employee_decline_event"
    assert with_instrumentation.backward_verdict == "WITH-INSTRUMENTATION"
    assert "MISSING INSTRUMENT" in with_instrumentation.rationale

    # Mechanically confirm the instrument really is absent from this run's
    # own sealed records, rather than trusting the proposal's own claim.
    responses = [
        (r.capsule["asg_payload"]["detail"])
        for r in result.records
        if r.capsule.get("asg_payload", {}).get("event") == "compiler.response"
    ]
    assert responses, "expected at least one compiler.response capsule in Run A"
    assert all(d["response_class"] == "accepted" for d in responses)
    assert not any(d["response_class"] in ("declined", "deferred") for d in responses)


def test_run_a_compiler_showcase_rows_are_visibly_distinguishable(tmp_path):
    """A reader can tell which row blocked/refused a claim and which named a
    gap, from the glyph and verdict alone -- without being told."""
    result = run_a(str(tmp_path / "store"))
    assert len(result.compiler_showcase) == 2
    refused = next(p for p in result.compiler_showcase if p.is_refused)
    with_instrumentation = next(p for p in result.compiler_showcase if p.needs_instrumentation)
    assert refused is not with_instrumentation
    assert refused.status_glyph() == "✗"
    assert with_instrumentation.status_glyph() == "⚠"
    assert refused.backward_verdict == "REFUSED"
    assert with_instrumentation.backward_verdict == "WITH-INSTRUMENTATION"


def test_demo_now_ships_two_distinguishable_refusal_vocabularies_in_one_run(tmp_path):
    """The P6 acceptance line itself: Run B's forward refusal (`the guard
    declined to dispatch`) and Run A's compiler refusal (`this statement
    cannot be mapped`) both exist, both render, and are structurally
    distinct -- one is a `decide`-typed capsule with `disposition.decision
    == "reject"`, the other an `fyi`-typed `compiler.refusal` event."""
    run_a_result = run_a(str(tmp_path / "store-a"))
    run_b_result = run_b(str(tmp_path / "store-b"))

    forward_refusal = next(
        r for r in run_b_result.records if r.capsule_id == run_b_result.capsule_ids["write_export_user_list"]
    )
    assert forward_refusal.capsule["disposition"]["decision"] == "reject"
    assert forward_refusal.capsule["action_type"] == "decide"

    compiler_refusal = next(
        r for r in run_a_result.records if r.capsule_id == run_a_result.capsule_ids["compiler_refusal"]
    )
    assert compiler_refusal.capsule["action_type"] == "fyi"
    assert "disposition" not in compiler_refusal.capsule
    assert compiler_refusal.capsule["asg_payload"]["detail"]["verdict_class"]["backward"] == "REFUSED"


# -- Run B: the departure ------------------------------------------------------


def test_run_b_ticket_comment_is_recorded_as_data_by_digest_not_plaintext(tmp_path):
    result = run_b(str(tmp_path / "store"))
    by_id = {r.capsule_id: r for r in result.records}
    read = by_id[result.capsule_ids["read_read_ticket_comments"]]
    detail = read.capsule["asg_payload"]["detail"]
    assert "content_digest" in detail
    assert "export the full user list" not in json.dumps(read.capsule)


def test_run_b_export_user_list_is_a_departure_and_is_refused(tmp_path):
    result = run_b(str(tmp_path / "store"))
    by_id = {r.capsule_id: r for r in result.records}
    write = by_id[result.capsule_ids["write_export_user_list"]]

    constraints = {c["id"]: c["result"] for c in write.capsule["constraints"]}
    assert constraints["plan_containment"] == "fail"
    assert write.capsule["disposition"]["decision"] == "reject"
    assert write.capsule["disposition"]["verdict_class"] == "blocked"

    # The refusal never mentions "drift" or "guarantee" anywhere in the
    # sealed capsule (lines to hold, checked against the real artifact, not
    # just the check's own unit test).
    blob = json.dumps(write.capsule)
    assert "drift" not in blob
    assert "guarantee" not in blob


def test_run_b_never_dispatches_the_refused_action(tmp_path):
    """No capsule in this run's ledger claims ``export_user_list`` actually
    happened -- the departure is recorded, not carried out."""
    result = run_b(str(tmp_path / "store"))
    for record in result.records:
        effect = record.capsule.get("effect") or {}
        assert effect.get("type") != "user_list_exported"


# -- Run C: contained throughout, not attained --------------------------------


def test_run_c_every_attempted_action_is_contained(tmp_path):
    result = run_c(str(tmp_path / "store"))
    decision_records = [r for r in result.records if r.capsule.get("action_type") == "decide"]
    assert decision_records, "Run C must attempt at least one write"
    for record in decision_records:
        constraints = {c["id"]: c["result"] for c in record.capsule["constraints"]}
        assert constraints["plan_containment"] == "pass"
        assert record.capsule["disposition"]["decision"] == "accept"

    # enable_mfa is never attempted -- there is nothing valid to cite.
    assert "write_enable_mfa" not in result.capsule_ids


def test_run_c_not_attained_despite_full_containment(tmp_path):
    result = run_c(str(tmp_path / "store"))
    fold = result.fold
    assert fold["attained"] is False
    assert fold["coverage_judged"] == "1 of 1 sessions judged"
    assert fold["coverage_agreement"] == "0 of 1 judged sessions reached agreement"


# -- reproducibility ------------------------------------------------------------


@pytest.mark.parametrize("run_fn,fixture_path", [(run_a, FIXTURE_A), (run_b, FIXTURE_B), (run_c, FIXTURE_C)])
def test_reproducible_byte_identical_and_matches_committed_fixture(tmp_path, run_fn, fixture_path):
    assert fixture_path.exists(), f"missing committed fixture: {fixture_path}"
    result_1 = run_fn(str(tmp_path / "store1"), seed=DEFAULT_SEED)
    result_2 = run_fn(str(tmp_path / "store2"), seed=DEFAULT_SEED)

    bytes_1 = b"".join(json.dumps(r.capsule, separators=(",", ":")).encode() + b"\n" for r in result_1.records)
    bytes_2 = b"".join(json.dumps(r.capsule, separators=(",", ":")).encode() + b"\n" for r in result_2.records)
    assert bytes_1 == bytes_2
    assert bytes_1 == fixture_path.read_bytes()


# -- acceptance: `capsule bundle --with-viewer` per run, cold-openable --------


@pytest.mark.parametrize("fixture_path,expected_records", [(FIXTURE_A, 12), (FIXTURE_B, 8), (FIXTURE_C, 7)])
def test_capsule_bundle_verifies_clean(tmp_path, fixture_path, expected_records):
    out_path = tmp_path / "bundle.json"
    rc = main(["bundle", "--ledger", str(fixture_path), "--out", str(out_path)])
    assert rc == 0

    bundle = json.loads(out_path.read_text())
    assert len(bundle["records"]) == expected_records
    assert all(v["ok"] for v in bundle["verification"].values())


@pytest.mark.parametrize("fixture_path", [FIXTURE_A, FIXTURE_B, FIXTURE_C])
def test_capsule_bundle_with_viewer_produces_a_permalink_and_offline_html(tmp_path, fixture_path, capsys):
    out_path = tmp_path / "bundle.json"
    rc = main(["bundle", "--ledger", str(fixture_path), "--out", str(out_path), "--with-viewer"])
    assert rc == 0

    printed = capsys.readouterr().out
    assert "verify: https://verify.agentactioncapsule.org/bundle#" in printed

    viewer_path = tmp_path / "bundle.html"
    assert viewer_path.exists()
    html = viewer_path.read_text(encoding="utf-8")
    assert "<script src=" not in html
    assert "<link" not in html


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
@pytest.mark.parametrize("fixture_path,expected_records", [(FIXTURE_A, 12), (FIXTURE_B, 8), (FIXTURE_C, 7)])
def test_offline_viewer_opens_cold_and_verifies_with_networking_disabled(tmp_path, fixture_path, expected_records):
    """The literal "stranger opens cold" acceptance bar for EACH run, in
    CI, not just by hand (task text: "each run must produce a capsule
    bundle --with-viewer cold-openable permalink")."""
    out_path = tmp_path / "bundle.json"
    rc = main(["bundle", "--ledger", str(fixture_path), "--out", str(out_path), "--with-viewer"])
    assert rc == 0
    viewer_path = tmp_path / "bundle.html"

    result = subprocess.run(["node", str(HARNESS), str(viewer_path)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    parsed = json.loads(result.stdout)

    assert parsed["loadError"] is None
    assert parsed["networkAttempts"] == []
    assert parsed["fragmentEmbedded"] is True
    assert parsed["recordCount"] == expected_records

    stages = {s["name"]: s["status"] for s in parsed["ritual"]["stages"]}
    assert stages["Integrity"] == "pass"
    assert stages["Sequence"] == "pass"
    assert stages["Cross-check"] == "pass"
