# SPDX-License-Identifier: Apache-2.0
"""`asg blame` golden-output tests."""
from __future__ import annotations

import json
from pathlib import Path

from asg_ledger.cli.main import main
from asg_ledger.ledger import LedgerStore

FIXTURES = Path(__file__).parent / "fixtures"
AMAURY = FIXTURES / "amaury_sample_ledger.jsonl"

APPROVE_ID = "705955419ca6f944a75db77ae2a59844fdd99d355866c6c1dbc4ebe655c024c7"  # seq 1, executed, standalone
CONFIRM_ID = "94c877c7ff0240cf7dafe2067f7016e5412d59b05f9eefa4baf90fc792f16142"  # seq 4, confirms seq 1


def test_blame_walks_confirms_chain_to_standalone_root(capsys):
    rc = main(["blame", CONFIRM_ID, "--ledger", str(AMAURY)])
    assert rc == 0
    out = capsys.readouterr().out
    assert f"capsule {CONFIRM_ID}  (target)" in out
    assert f"capsule {APPROVE_ID}" in out
    assert out.index(CONFIRM_ID) < out.index(APPROVE_ID)
    assert "chain.relation='confirms'" in out
    assert "2 hop(s) in chain · root reached — this record carries no chain (standalone)" in out
    assert out.rstrip().endswith(f"≡ asg blame {CONFIRM_ID}")


def test_blame_prefix_target(capsys):
    rc = main(["blame", CONFIRM_ID[:10], "--ledger", str(AMAURY)])
    assert rc == 0
    out = capsys.readouterr().out
    assert f"capsule {CONFIRM_ID}  (target)" in out


def test_blame_target_not_found(capsys):
    rc = main(["blame", "deadbeef", "--ledger", str(AMAURY)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "no such capsule 'deadbeef'" in err


def test_blame_max_depth_truncates(capsys):
    rc = main(["blame", CONFIRM_ID, "--ledger", str(AMAURY), "--max-depth", "1"])
    assert rc == 0
    out = capsys.readouterr().out
    assert f"capsule {CONFIRM_ID}  (target)" in out
    assert f"capsule {APPROVE_ID}" not in out  # not walked -- only named in the truncation detail
    assert "1 hop(s) in chain · walk truncated at --max-depth=1" in out
    assert f"parent_capsule_id={APPROVE_ID!r} not walked" in out


def test_blame_json_flag(capsys):
    rc = main(["blame", CONFIRM_ID, "--ledger", str(AMAURY), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["target"] == CONFIRM_ID
    assert [h["capsule_id"] for h in payload["hops"]] == [CONFIRM_ID, APPROVE_ID]
    assert payload["hops"][0]["relation"] == "confirms"
    assert payload["terminal"] == {"kind": "standalone", "detail": None}


def _capsule(capsule_id, *, parent=None, relation=None, verdict="executed", ts="2026-01-01T00:00:00Z"):
    cap = {
        "capsule_id": capsule_id,
        "operator": "acme",
        "developer": "agent-1",
        "action_type": "approve_purchase",
        "timestamp": ts,
        "disposition": {"verdict_class": verdict},
    }
    if parent is not None:
        cap["chain"] = {"parent_capsule_id": parent, "relation": relation}
    return cap


def test_blame_reports_a_chain_gap_not_a_crash(tmp_path, capsys):
    store = LedgerStore(tmp_path)
    missing_parent = "a" * 64
    child_id = "b" * 64
    store.append(_capsule(child_id, parent=missing_parent, relation="confirms"), consequential=False)
    store.close()

    rc = main(["blame", child_id, "--ledger", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert f"chain gap — parent_capsule_id {missing_parent!r} not found in this ledger" in out
    assert "browsable window:" in out


def test_blame_stops_cleanly_at_epoch_opens_boundary(tmp_path, capsys):
    store = LedgerStore(tmp_path)
    opener_id = "c" * 64
    child_id = "d" * 64
    # epoch_opens is a legal chain-start (agent_action_capsule.history registry) --
    # its own parent_capsule_id, if any, is out of scope, never a gap.
    store.append(_capsule(opener_id, parent="e" * 64, relation="epoch_opens"), consequential=False)
    store.append(_capsule(child_id, parent=opener_id, relation="confirms"), consequential=False)
    store.close()

    rc = main(["blame", child_id, "--ledger", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert f"capsule {opener_id}" in out
    assert "epoch boundary reached — chain.relation=epoch_opens is a legal chain-start, not a gap" in out
    assert "chain gap" not in out


def test_blame_detects_a_cycle(tmp_path, capsys):
    store = LedgerStore(tmp_path)
    a_id, b_id = "1" * 64, "2" * 64
    store.append(_capsule(a_id, parent=b_id, relation="confirms"), consequential=False)
    store.append(_capsule(b_id, parent=a_id, relation="confirms"), consequential=False)
    store.close()

    rc = main(["blame", a_id, "--ledger", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert f"cycle detected — chain re-visits capsule_id {a_id!r}" in out
