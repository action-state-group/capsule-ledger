# SPDX-License-Identifier: Apache-2.0
"""`capsule lens` golden-output tests.

Acceptance per the task: each lens must catch a real instance of what it
claims to catch, not just run without crashing.

  - novelty:      the amaury fixture's procurement agent runs four distinct
                   action verbs in sequence -- each one after the first is a
                   real novel-verb instance.
  - shape/storm:   the nanda tax-audit-style fixture (`nanda_transaction_
                   ledger.jsonl`) is 36 near-identical `record_transaction`
                   actions by one agent within milliseconds -- a real retry
                   storm.
  - shape/cycle:   a constructed A/B/A/B/A/B sequence (no existing fixture
                   has one) -- a real cyclic pattern.
  - blast-radius:  the amaury fixture's `confirm_purchase` record cites
                   `approve_purchase` via `chain.relation=confirms` -- a
                   real downstream citer.
"""
from __future__ import annotations

import json
from pathlib import Path

from asg_ledger.cli.main import main
from asg_ledger.ledger import LedgerStore

FIXTURES = Path(__file__).parent / "fixtures"
AMAURY = FIXTURES / "amaury_sample_ledger.jsonl"
NANDA = FIXTURES / "nanda_transaction_ledger.jsonl"

APPROVE_ID = "705955419ca6f944a75db77ae2a59844fdd99d355866c6c1dbc4ebe655c024c7"  # seq 1, executed
TRANSFER_ID = "cd0692b3349fadfeabe618008301b625059cc819eeb5ca1fb660699be9b6504e"  # seq 2, blocked
REPORT_ID = "ac0d53a6fef41879e31faf20ae7f73b9d1facf07640c3c1ffc5ae4d8ab26d301"  # seq 3, executed
CONFIRM_ID = "94c877c7ff0240cf7dafe2067f7016e5412d59b05f9eefa4baf90fc792f16142"  # seq 4, confirms seq 1


# -- novelty -----------------------------------------------------------------


def test_novelty_flags_new_verbs_for_the_same_agent(capsys):
    rc = main(["lens", "novelty", "--ledger", str(AMAURY)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "3 novel action(s):" in out
    # the agent's first-ever action (approve_purchase) has no history to be unlike -- never flagged
    assert APPROVE_ID[:16] not in out.split("3 novel action(s):")[1].split("≡")[0]
    assert TRANSFER_ID[:16] in out
    assert REPORT_ID[:16] in out
    assert CONFIRM_ID[:16] in out
    assert "verb='transfer_funds'" in out
    assert "prior verbs: approve_purchase" in out
    assert out.rstrip().endswith("≡ capsule lens novelty --min-history 1")


def test_novelty_min_history_raises_the_no_baseline_floor(capsys):
    # with min_history=3, only the 4th record has enough prior history to be judged
    rc = main(["lens", "novelty", "--ledger", str(AMAURY), "--min-history", "3"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "1 novel action(s):" in out
    assert CONFIRM_ID[:16] in out
    assert TRANSFER_ID[:16] not in out.split("1 novel action(s):")[1].split("≡")[0]


def test_novelty_no_findings_on_a_uniform_ledger(capsys):
    # the tax-audit fixture is 36 identical-verb records by one agent -- no novelty after the first
    rc = main(["lens", "novelty", "--ledger", str(NANDA)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "no novel actions found" in out


def test_novelty_json_flag(capsys):
    rc = main(["lens", "novelty", "--ledger", str(AMAURY), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert [f["capsule_id"] for f in payload["findings"]] == [TRANSFER_ID, REPORT_ID, CONFIRM_ID]
    assert payload["findings"][0]["prior_verbs"] == ["approve_purchase"]


def test_novelty_agent_filter(capsys):
    rc = main(["lens", "novelty", "--ledger", str(AMAURY), "--agent", "nobody"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "no novel actions found" in out


# -- shape: retry storms -------------------------------------------------


def test_shape_detects_the_real_retry_storm_in_the_tax_audit_fixture(capsys):
    rc = main(["lens", "shape", "--ledger", str(NANDA)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "1 retry storm(s):" in out
    assert "biz_capsule-0" in out
    assert "verb='record_transaction'" in out
    assert "36x in" in out
    assert "(seq #1–#36)" in out
    assert "no retry storms or cyclic patterns found" not in out


def test_shape_min_repeats_can_suppress_the_storm(capsys):
    rc = main(["lens", "shape", "--ledger", str(NANDA), "--min-repeats", "100"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "no retry storms or cyclic patterns found" in out


def test_shape_zero_window_suppresses_the_storm(capsys):
    # the 36 nanda records span ~24ms -- a 0s window is stricter than that real span
    rc = main(["lens", "shape", "--ledger", str(NANDA), "--window", "0s"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "no retry storms or cyclic patterns found" in out


def test_shape_no_findings_on_amaury(capsys):
    # amaury's 4 records are 4 distinct verbs, no repeats and no alternation
    rc = main(["lens", "shape", "--ledger", str(AMAURY)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "no retry storms or cyclic patterns found" in out


def test_shape_json_flag(capsys):
    rc = main(["lens", "shape", "--ledger", str(NANDA), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["retry_storms"]) == 1
    assert payload["retry_storms"][0]["verb"] == "record_transaction"
    assert len(payload["retry_storms"][0]["capsule_ids"]) == 36
    assert payload["cycles"] == []


def test_shape_bad_window_is_a_clean_failure(capsys):
    rc = main(["lens", "shape", "--ledger", str(NANDA), "--window", "notaduration"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "must match" in err


# -- shape: cycles --------------------------------------------------------


def _capsule(capsule_id, verb, developer="agent-1", ts="2026-01-01T00:00:00Z"):
    return {
        "capsule_id": capsule_id,
        "operator": "acme",
        "developer": developer,
        "action_id": f"{verb}/{capsule_id[:8]}",
        "action_type": "decide",
        "timestamp": ts,
        "disposition": {"verdict_class": "executed"},
    }


def test_shape_detects_a_real_ab_cycle(tmp_path, capsys):
    store = LedgerStore(tmp_path)
    verbs = ["poll_status", "retry_dispatch", "poll_status", "retry_dispatch", "poll_status", "retry_dispatch"]
    for i, verb in enumerate(verbs):
        store.append(_capsule(f"{i:064d}", verb, ts=f"2026-01-01T00:00:{i:02d}Z"), consequential=False)
    store.close()

    rc = main(["lens", "shape", "--ledger", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "1 cyclic pattern(s):" in out
    assert "'poll_status' <-> 'retry_dispatch'" in out
    assert "6x" in out
    assert "(seq #1–#6)" in out


def test_shape_short_alternation_is_not_a_cycle(tmp_path, capsys):
    store = LedgerStore(tmp_path)
    # only 3 alternating records -- below the default min-cycle-length of 4
    for i, verb in enumerate(["a", "b", "a"]):
        store.append(_capsule(f"{i:064d}", verb, ts=f"2026-01-01T00:00:{i:02d}Z"), consequential=False)
    store.close()

    rc = main(["lens", "shape", "--ledger", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "no retry storms or cyclic patterns found" in out


# -- blast-radius ----------------------------------------------------------


def test_blast_radius_finds_the_real_downstream_citer(capsys):
    rc = main(["lens", "blast-radius", APPROVE_ID, "--ledger", str(AMAURY)])
    assert rc == 0
    out = capsys.readouterr().out
    assert f"capsule {APPROVE_ID}" in out
    assert "blast radius: 1 downstream record(s)" in out
    assert CONFIRM_ID[:16] in out
    assert "chain.relation='confirms'" in out


def test_blast_radius_zero_for_a_leaf_record(capsys):
    rc = main(["lens", "blast-radius", CONFIRM_ID, "--ledger", str(AMAURY)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "blast radius: 0 downstream record(s)" in out


def test_blast_radius_prefix_target(capsys):
    rc = main(["lens", "blast-radius", APPROVE_ID[:10], "--ledger", str(AMAURY)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "blast radius: 1 downstream record(s)" in out


def test_blast_radius_target_not_found(capsys):
    rc = main(["lens", "blast-radius", "deadbeef", "--ledger", str(AMAURY)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "no such capsule 'deadbeef'" in err


def test_blast_radius_json_flag(capsys):
    rc = main(["lens", "blast-radius", APPROVE_ID, "--ledger", str(AMAURY), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["target"] == APPROVE_ID
    assert payload["count"] == 1
    assert payload["downstream"][0]["capsule_id"] == CONFIRM_ID


def test_blast_radius_is_transitive(tmp_path, capsys):
    store = LedgerStore(tmp_path)
    root_id = "a" * 64
    mid_id = "b" * 64
    leaf_id = "c" * 64
    root = _capsule(root_id, "open_case")
    mid = dict(_capsule(mid_id, "escalate"), chain={"parent_capsule_id": root_id, "relation": "confirms"})
    leaf = dict(_capsule(leaf_id, "close_case"), chain={"parent_capsule_id": mid_id, "relation": "confirms"})
    store.append(root, consequential=False)
    store.append(mid, consequential=False)
    store.append(leaf, consequential=False)
    store.close()

    rc = main(["lens", "blast-radius", root_id, "--ledger", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "blast radius: 2 downstream record(s)" in out
    assert mid_id[:16] in out
    assert leaf_id[:16] in out
