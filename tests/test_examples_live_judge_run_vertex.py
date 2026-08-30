# SPDX-License-Identifier: Apache-2.0
"""``[ldg-bp-vertex-scorer-live-run]``'s live-run script, exercised against
the REAL demo-chunk-1 tau2-airline corpus fixture -- skipped, not failed,
when that sibling worktree is not present (same honesty convention
``test_airline_pack_desk.py`` uses).

**No real Vertex call is ever made here** (MONEY-PATH guard: the coder's own
verification of this task must never spend Steven's Vertex quota) -- every
test monkeypatches ``judge.scorers.vertex``'s ``default_access_token``/
``default_http_post`` module attributes with a fake token and a fake
in-process HTTP responder before calling ``main()``.

``[ldg-bp-vertex-prompt-drafting-small-run]`` #98-review fix: the spend
confirm gate (``confirm_live_spend``) is exercised directly here too --
every test that reaches a real (faked) Vertex call either supplies
``--dry-run-was-reviewed`` alongside ``--yes``, or monkeypatches ``input``
to answer the gate explicitly, so none of these tests silently rely on the
gate being a no-op."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from capsule_ledger.examples import live_judge_run_vertex as live_mod
from capsule_ledger.judge.scorers import vertex as vertex_module
from capsule_ledger.ledger import LedgerStore

CORPUS_PATH = (
    Path(__file__).resolve().parents[3]
    / "record-grounding-bench"
    / "demo-chunk1-tau2-corpus"
    / "data"
    / "fixtures"
    / "tau2-airline-corpus-v1"
)

pytestmark = pytest.mark.skipif(
    not CORPUS_PATH.is_dir(),
    reason=(
        f"real demo-chunk-1 tau2-airline corpus fixture not found at {CORPUS_PATH} -- "
        "checkout record-grounding-bench's demo/chunk1-tau2-corpus worktree as a sibling "
        "of capsule-ledger's own _worktrees/ to run this integration test"
    ),
)


def _fake_vertex(monkeypatch, *, label: str = "pass", confidence: float = 0.8):
    calls = []
    monkeypatch.setattr(vertex_module, "default_access_token", lambda: "fake-adc-token")

    def fake_http_post(url, payload, headers):
        calls.append((url, payload, dict(headers)))
        text = json.dumps({"label": label, "confidence": confidence, "rationale": "fake"})
        return {"candidates": [{"content": {"parts": [{"text": text}]}}]}

    monkeypatch.setattr(vertex_module, "default_http_post", fake_http_post)
    return calls


def test_dry_run_reports_the_call_shape_without_any_vertex_call(tmp_path, capsys, monkeypatch):
    calls = _fake_vertex(monkeypatch)
    rc = live_mod.main(
        [
            "--corpus", str(CORPUS_PATH), "--out", str(tmp_path / "run"),
            "--limit-terms", "2", "--limit-sessions", "2", "--yes", "--dry-run",
        ]
    )
    assert rc == 0
    assert calls == []  # dry run never calls the (fake) transport
    out = capsys.readouterr().out
    assert "2 term(s) x 2 session(s)" in out
    assert "4 call(s) made (dry run)" in out


def test_default_scope_is_two_terms_and_ten_sessions(tmp_path, capsys, monkeypatch):
    calls = _fake_vertex(monkeypatch)
    rc = live_mod.main(["--corpus", str(CORPUS_PATH), "--out", str(tmp_path / "run"), "--yes", "--dry-run"])
    assert rc == 0
    assert calls == []
    out = capsys.readouterr().out
    assert "2 term(s) x 10 session(s)" in out


def test_live_run_seals_verifiable_judgment_capsules_for_all_four_terms(tmp_path, capsys, monkeypatch):
    from agent_action_capsule import verify as verify_capsule

    calls = _fake_vertex(monkeypatch, label="pass", confidence=0.8)
    out_root = tmp_path / "run"
    rc = live_mod.main(
        [
            "--corpus", str(CORPUS_PATH), "--out", str(out_root),
            "--all-terms", "--limit-sessions", "1", "--yes", "--dry-run-was-reviewed",
        ]
    )
    assert rc == 0

    assert len(calls) == 4  # 4 terms x 1 session, one call per (term, session) -- never per label
    for url, _payload, headers in calls:
        assert url.endswith(":generateContent")
        assert headers["x-goog-user-project"] == "fluxxom"

    store = LedgerStore(out_root / "live-ledger")
    try:
        records = list(store.scan())
    finally:
        store.close()
    judgments = [r for r in records if r.capsule.get("asg_payload", {}).get("event") == "judge_judgment"]
    assert len(judgments) == 4
    for r in judgments:
        detail = r.capsule["asg_payload"]["detail"]
        assert detail["label"] == "pass"
        assert detail["model_id"] == "vertex_ai/gemini-2.5-flash"

    ids = [r.capsule["capsule_id"] for r in records]
    for r in records:
        assert verify_capsule(r.capsule, store=ids).ok

    out = capsys.readouterr().out
    assert "judgment report -- 4 call(s) made" in out


def test_yes_alone_skips_only_the_t1_t3_approve_prompts(tmp_path, monkeypatch):
    # No stdin is provided at all -- if main() ever blocked on input() at T1/T3 despite
    # --yes, this test would hang/fail rather than pass silently. It still needs to answer
    # the SEPARATE spend-confirm gate, which --yes alone does not skip.
    _fake_vertex(monkeypatch)
    monkeypatch.setattr(live_mod, "input", lambda prompt="": "y", raising=False)
    rc = live_mod.main(
        ["--corpus", str(CORPUS_PATH), "--out", str(tmp_path / "run"), "--limit-sessions", "1", "--yes"]
    )
    assert rc == 0


def test_yes_alone_does_not_skip_the_spend_confirm_gate(tmp_path, monkeypatch):
    """The #98-review fix's core guarantee: `--yes` fires the T1/T3 'approve'
    gates but must NOT fire real, billed Vertex calls without a separate
    confirm. Answering 'n' at that gate must abort with zero real calls."""
    calls = _fake_vertex(monkeypatch)
    prompts_seen = []

    def fake_input(prompt=""):
        prompts_seen.append(prompt)
        return "n"

    monkeypatch.setattr(live_mod, "input", fake_input, raising=False)
    with pytest.raises(SystemExit):
        live_mod.main(
            ["--corpus", str(CORPUS_PATH), "--out", str(tmp_path / "run"), "--limit-sessions", "1", "--yes"]
        )
    assert calls == []  # aborted before any real (faked) Vertex call
    assert any("BILLED" in p for p in prompts_seen)  # the spend-confirm prompt was actually reached


def test_dry_run_was_reviewed_alone_does_not_skip_the_spend_confirm_gate(tmp_path, monkeypatch):
    # --dry-run-was-reviewed without --yes still blocks at T1/T3 AND the spend gate;
    # confirms neither flag alone is sufficient -- only BOTH together skip the gate.
    calls = _fake_vertex(monkeypatch)
    monkeypatch.setattr(live_mod, "input", lambda prompt="": "approve", raising=False)
    with pytest.raises(SystemExit):
        # answering "approve" satisfies T1/T3 but NOT the spend gate's y/N -- so the
        # spend gate itself will see "approve", which is not "y"/"yes", and abort.
        live_mod.main(
            [
                "--corpus", str(CORPUS_PATH), "--out", str(tmp_path / "run"),
                "--limit-sessions", "1", "--dry-run-was-reviewed",
            ]
        )
    assert calls == []


def test_yes_and_dry_run_was_reviewed_together_skip_the_spend_confirm_gate(tmp_path, monkeypatch):
    # No stdin provided at all -- if the gate ever blocked on input() despite both flags,
    # this would hang/fail rather than pass silently.
    calls = _fake_vertex(monkeypatch)
    rc = live_mod.main(
        [
            "--corpus", str(CORPUS_PATH), "--out", str(tmp_path / "run"),
            "--limit-sessions", "1", "--yes", "--dry-run-was-reviewed",
        ]
    )
    assert rc == 0
    assert len(calls) == 2  # default --limit-terms 2 x 1 session


def test_spend_confirm_gate_prints_the_call_and_cost_estimate(tmp_path, capsys, monkeypatch):
    _fake_vertex(monkeypatch)
    rc = live_mod.main(
        [
            "--corpus", str(CORPUS_PATH), "--out", str(tmp_path / "run"),
            "--limit-sessions", "1", "--yes", "--dry-run-was-reviewed",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "2 term(s) x 1 session(s) = 2 call(s), est ~$" in out
