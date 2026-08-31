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


# -- [account-fold-core-unify] conformance -----------------------------------


def test_real_run_seals_a_conformant_model_assisted_account_per_term(tmp_path, capsys, monkeypatch):
    _fake_vertex(monkeypatch, label="pass", confidence=0.9)
    out_root = tmp_path / "run"
    rc = live_mod.main(
        [
            "--corpus", str(CORPUS_PATH), "--out", str(out_root),
            "--limit-sessions", "1", "--yes", "--dry-run-was-reviewed",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "[account-fold-core-unify] conformant model-assisted account(s) sealed:" in out
    assert "A1:" in out and "A3b:" in out
    assert "definition_digest:" in out
    assert "asserted_result:    {'pass': 1}" in out

    # A checkpoint sealed onto the run's own live ledger (sidecar file, not a
    # ledger capsule) -- the coverage_root the accounts cite.
    checkpoints = sorted((out_root / "live-ledger" / "checkpoints").glob("*.json"))
    assert len(checkpoints) == 1


def test_dry_run_seals_no_account_and_no_checkpoint(tmp_path, capsys, monkeypatch):
    _fake_vertex(monkeypatch)
    out_root = tmp_path / "run"
    rc = live_mod.main(
        ["--corpus", str(CORPUS_PATH), "--out", str(out_root), "--limit-sessions", "1", "--yes", "--dry-run"]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "[account-fold-core-unify]" not in out
    assert not (out_root / "live-ledger" / "checkpoints").exists()


def test_sealed_account_provenance_names_the_real_model_and_prompt_digest(tmp_path):
    """Isolated unit test of ``seal_conformant_accounts`` itself -- a fresh
    ledger + two real (StaticScorer, no network) judgment capsules, so this
    doesn't rely on ``main()``'s own T1/T3/checkpoint side effects (a second
    ``seal_conformant_accounts`` call against an already-checkpointed ledger
    with no new records would raise a rollback error -- that's a real
    invariant, not a bug, so this test avoids it by building its own fixture
    ledger instead of reusing one ``main()`` already checkpointed)."""
    from collections import Counter

    from capsule_ledger.guards.signing import LocalSigner
    from capsule_ledger.judge import JudgeEvidence, JudgeHarness
    from capsule_ledger.judge.prompt import JudgePromptDefinition
    from capsule_ledger.judge.scorers.static import StaticScorer
    from capsule_ledger.ledger import LedgerStore

    prompt = JudgePromptDefinition(prompt_id="a1/1.0.0", label_set=("pass", "fail"), instructions="judge it")
    signer = LocalSigner(key_id="test-key", secret=b"test-secret")
    store = LedgerStore(tmp_path / "fixture-ledger")
    try:
        harness = JudgeHarness(
            ledger=store, prompt=prompt, scorer=StaticScorer(responses={}, default=("fail", 0.6)),
            operator="test", developer="test@v1", signer_provider=lambda: signer,
        )
        judgments = [
            harness.run(evidence=JudgeEvidence(session_id=f"s{i}", turn_capsule_ids=(f"cap-{i}",), evidence_text=f"ev{i}"))
            for i in range(2)
        ]
        accounts = live_mod.seal_conformant_accounts({"A1": judgments}, Counter({("A1", "fail"): 2}), store, signer)
    finally:
        store.close()

    assert set(accounts) == {"A1"}
    doc = accounts["A1"]
    assert doc["derivation"]["derivation_class"] == "model_assisted"
    assert doc["selection"]["kind"] == "range"
    assert doc["selection"]["input_identity"]["range"] == [judgments[0].seq, judgments[-1].seq]
    assert "references" not in doc["selection"]["input_identity"]  # range identity, never per-member digests
    assert doc["provenance"]["model_id"] == "static-scorer/deterministic"
    assert doc["provenance"]["prompt_digest"] == judgments[0].capsule["asg_payload"]["detail"]["prompt_digest"]
    assert "2 independent per-call seed" in doc["provenance"]["entropy"]
    # [t2r-live-judge-run] review fix: an operator-chosen seed is a reproducibility
    # handle, not a grind-resistance guarantee -- this label must stay honest.
    assert "seed_source=operator_chosen" in doc["provenance"]["entropy"]
    assert "NOT grind-resistant" in doc["provenance"]["entropy"]


def test_no_overclaimed_entropy_binding_language_anywhere_in_the_module():
    """Regression guard for the reviewed overclaim: this module must never
    claim a "real"/grind-resistant entropy binding for an operator-chosen
    seed -- see ``judge/scorers/vertex.py``'s and this module's own
    docstrings for why. A future edit that reintroduces that phrasing should
    fail this test, not slip through review again."""
    import inspect

    source = inspect.getsource(live_mod)
    assert "real entropy binding" not in source
    assert "a grind-resistant" not in source  # only "NOT grind-resistant" may appear


def test_account_construction_is_fail_closed_on_missing_provenance():
    """Not this script's own bug surface -- the core's own contract, exercised
    here so a future change to how this script calls ``build_account`` can't
    silently start minting a provenance-free model-assisted account (the
    exact failure mode ``[account-fold-core-unify]`` designed fail-closed
    construction to catch)."""
    from capsule_ledger.folds import DERIVATION_MODEL_ASSISTED, ReadField, Reduce, build_account
    from capsule_ledger.folds.account_core import AccountConstructionError, Coverage, Selection
    from capsule_ledger.folds.definition import FoldDefinition

    fold = FoldDefinition(
        fold_id="test.fold/1.0.0",
        reads=(ReadField(path="asg_payload.detail.label", erasure_class="commitment-ok"),),
        reduce=Reduce(reducer="count"),
        emit="test.count",
        derivation_class=DERIVATION_MODEL_ASSISTED,
    )
    with pytest.raises(AccountConstructionError):
        build_account(
            definition=fold.to_account_definition(),
            selection=Selection(kind="range", coverage=Coverage(coverage_root="deadbeef", range=(1, 2))),
            asserted_result={"fail": 2},
            provenance=None,  # model_assisted with no provenance -- must refuse
        )
