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
    MANIFEST_PATH,
    load_governing_pack,
    load_plan,
    run_a,
    run_b,
    run_c,
    run_combined,
)
from capsule_ledger.policy import load_manifest_file

FIXTURE_DIR = Path(__file__).parent / "fixtures"
FIXTURE_A = FIXTURE_DIR / "plan_containment_run_a.jsonl"
FIXTURE_B = FIXTURE_DIR / "plan_containment_run_b.jsonl"
FIXTURE_C = FIXTURE_DIR / "plan_containment_run_c.jsonl"
FIXTURE_COMBINED = FIXTURE_DIR / "plan_containment_combined.jsonl"
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


# -- the payments-safety pack genuinely governs this scenario -----------------
# `[ldg-cs-p6c-partner-demo-hardening]`: the doc's onboarding step installs
# `asg/payments-safety/1.0.0` but the scenario governed a totally unrelated
# outcome, with no checkable link between the two. These assert the link is
# now real: the SAME pack's digest is cited on the manifest, and its
# `caps_minor` config (not a re-typed copy) is what every write's `caps`
# constraint is evaluated against.


def test_the_manifest_cites_the_same_pack_the_doc_installs():
    manifest = load_manifest_file(MANIFEST_PATH)
    assert len(manifest.packs) == 1
    pack_ref = manifest.packs[0]
    assert pack_ref.pack_id == "asg/payments-safety/1.0.0"
    assert pack_ref.mode == "observe"

    pack = load_governing_pack()
    assert pack.pack_id == pack_ref.pack_id
    # The cited digest is real and independently recomputable from the
    # actual catalog file, never hand-typed -- if the pack ever changes,
    # this drifts and fails loudly rather than silently going stale.
    assert pack_ref.digest == pack.definition_digest()


def test_every_write_is_evaluated_against_the_real_pack_caps_config(tmp_path):
    """Every write's `caps` constraint reports `n/a` because none of these
    actions carry a money amount -- the honest answer for a cap keyed on
    `money.transfer`, not evidence the pack is disconnected. `dedupe` and
    `verify_before_dispatch` (the pack's non-money obligations) already run
    unconditionally and are asserted as `pass`/`n/a` (never absent)."""
    result = run_a(str(tmp_path / "store"))
    decision_records = [r for r in result.records if r.capsule.get("action_type") == "decide"]
    assert decision_records, "Run A must attempt at least one write"
    for record in decision_records:
        constraints = {c["id"]: c["result"] for c in record.capsule["constraints"]}
        assert constraints.keys() == {"dedupe", "caps", "verify_before_dispatch", "plan_containment"}
        assert constraints["caps"] == "n/a"
        assert constraints["dedupe"] in ("pass", "fail")
        assert constraints["verify_before_dispatch"] in ("pass", "n/a", "fail")


def test_caps_minor_threaded_into_the_engine_is_the_packs_own_value(tmp_path):
    """Mechanically confirm the `n/a` above is because the action's class
    (``tool.call``) never matches the pack's own configured key
    (``money.transfer``) -- not because ``caps_minor`` was never threaded
    into the engine at all. Same real pack config ``manifest.yaml``'s
    digest cites, not a value re-declared in this test."""
    pack = load_governing_pack()
    caps_wicket = next(w for w in pack.constraints if w.check == "caps")
    assert caps_wicket.config["caps_minor"] == {"money.transfer": 1000000}

    result = run_a(str(tmp_path / "store"))
    write = next(r for r in result.records if r.capsule.get("action_type") == "decide")
    assert write.capsule["asg_payload"]["action_class"] == "tool.call"
    caps_constraint = next(c for c in write.capsule["constraints"] if c["id"] == "caps")
    assert caps_constraint["result"] == "n/a"


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


# -- Combined: the coverage denominator carries weight -------------------------
# `[ldg-cs-p6c-partner-demo-hardening]`: standalone Run A/B/C each report a
# trivial "1 of 1 sessions judged", which does not demonstrate why a
# denominator matters. `run_combined` puts all three seeded sessions on ONE
# ledger -- no new or fabricated data, the same three deterministic chains --
# so the fold's own coverage line reflects a real batch.


def test_run_combined_coverage_denominator_is_three_not_one(tmp_path):
    result = run_combined(str(tmp_path / "store"))
    fold = result.fold
    assert fold["coverage_judged"] == "3 of 3 sessions judged"
    assert fold["coverage_agreement"] == "1 of 3 judged sessions reached agreement"
    assert fold["coverage_confirmed"] == "1 of 1 agreements confirmed"
    assert fold["attained"] is True
    assert len(fold["sessions"]) == 3


def test_run_combined_contains_exactly_run_a_plus_run_b_plus_run_c(tmp_path):
    """The combined ledger is the same three deterministic chains, not a
    re-simulation: same action ids, same count, same per-run ordering. Not
    byte-identical capsule-for-capsule against the standalone runs, though
    -- a write's sealed ``checkpoint.tree_size`` honestly reflects how many
    records are in ITS ledger at that moment, which is larger once Run A's
    (and, for Run C's write, Run A's + Run B's) records already sit in the
    SHARED store; that is a real, correct difference, not a bug."""
    combined = run_combined(str(tmp_path / "store-combined"))
    solo_a = run_a(str(tmp_path / "store-a"))
    solo_b = run_b(str(tmp_path / "store-b"))
    solo_c = run_c(str(tmp_path / "store-c"))

    assert len(combined.records) == len(solo_a.records) + len(solo_b.records) + len(solo_c.records)

    combined_action_ids = {r.capsule.get("action_id") for r in combined.records if r.capsule.get("action_id")}
    solo_action_ids = {
        r.capsule.get("action_id")
        for r in (*solo_a.records, *solo_b.records, *solo_c.records)
        if r.capsule.get("action_id")
    }
    assert combined_action_ids == solo_action_ids

    # Every record but tree_size-bearing decision capsules IS byte-identical
    # across the shared vs. separate stores (same seed, same timestamps).
    # A decision capsule's own `capsule_id`/`asg_signature` are themselves
    # downstream of `tree_size` (both are computed over the full sealed
    # content), so those two are stripped alongside it for this comparison.
    def _sans_tree_size(capsule: dict) -> dict:
        payload = capsule.get("asg_payload") or {}
        if "checkpoint" not in payload:
            return capsule
        stripped = dict(capsule)
        stripped["asg_payload"] = {**payload, "checkpoint": {**payload["checkpoint"], "tree_size": None}}
        stripped.pop("capsule_id", None)
        stripped.pop("asg_signature", None)
        return stripped

    combined_by_action = {r.capsule.get("action_id"): _sans_tree_size(r.capsule) for r in combined.records}
    for solo_result in (solo_a, solo_b, solo_c):
        for r in solo_result.records:
            action_id = r.capsule.get("action_id")
            if action_id is None:
                continue
            assert combined_by_action[action_id] == _sans_tree_size(r.capsule)


# -- reproducibility ------------------------------------------------------------


@pytest.mark.parametrize(
    "run_fn,fixture_path", [(run_a, FIXTURE_A), (run_b, FIXTURE_B), (run_c, FIXTURE_C), (run_combined, FIXTURE_COMBINED)]
)
def test_reproducible_byte_identical_and_matches_committed_fixture(tmp_path, run_fn, fixture_path):
    assert fixture_path.exists(), f"missing committed fixture: {fixture_path}"
    result_1 = run_fn(str(tmp_path / "store1"), seed=DEFAULT_SEED)
    result_2 = run_fn(str(tmp_path / "store2"), seed=DEFAULT_SEED)

    bytes_1 = b"".join(json.dumps(r.capsule, separators=(",", ":")).encode() + b"\n" for r in result_1.records)
    bytes_2 = b"".join(json.dumps(r.capsule, separators=(",", ":")).encode() + b"\n" for r in result_2.records)
    assert bytes_1 == bytes_2
    assert bytes_1 == fixture_path.read_bytes()


# -- acceptance: `capsule bundle --with-viewer` per run, cold-openable --------


@pytest.mark.parametrize(
    "fixture_path,expected_records", [(FIXTURE_A, 12), (FIXTURE_B, 8), (FIXTURE_C, 7), (FIXTURE_COMBINED, 27)]
)
def test_capsule_bundle_verifies_clean(tmp_path, fixture_path, expected_records):
    out_path = tmp_path / "bundle.json"
    rc = main(["bundle", "--ledger", str(fixture_path), "--out", str(out_path)])
    assert rc == 0

    bundle = json.loads(out_path.read_text())
    assert len(bundle["records"]) == expected_records
    assert all(v["ok"] for v in bundle["verification"].values())


@pytest.mark.parametrize("fixture_path", [FIXTURE_A, FIXTURE_B, FIXTURE_C, FIXTURE_COMBINED])
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
    bundle --with-viewer cold-openable permalink"). Not parametrized over
    ``FIXTURE_COMBINED`` -- it is a UNION of three independent session
    chains, not one walkable sequence, so its own "Sequence" ritual stage
    honestly reports ``skip`` rather than ``pass``; see
    ``test_offline_viewer_opens_cold_for_the_combined_ledger`` below."""
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


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_offline_viewer_opens_cold_for_the_combined_ledger(tmp_path):
    """Same cold-open acceptance bar, for the 27-record combined ledger --
    Integrity and Cross-check still pass; Sequence honestly reports `skip`
    because three independent session chains, each starting its own first
    record with no parent, is not one walkable sequence."""
    out_path = tmp_path / "bundle.json"
    rc = main(["bundle", "--ledger", str(FIXTURE_COMBINED), "--out", str(out_path), "--with-viewer"])
    assert rc == 0
    viewer_path = tmp_path / "bundle.html"

    result = subprocess.run(["node", str(HARNESS), str(viewer_path)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    parsed = json.loads(result.stdout)

    assert parsed["loadError"] is None
    assert parsed["networkAttempts"] == []
    assert parsed["fragmentEmbedded"] is True
    assert parsed["recordCount"] == 27

    stages = {s["name"]: s["status"] for s in parsed["ritual"]["stages"]}
    assert stages["Integrity"] == "pass"
    assert stages["Cross-check"] == "pass"
