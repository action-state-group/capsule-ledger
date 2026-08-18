# SPDX-License-Identifier: Apache-2.0
"""``capsule judge run`` / ``capsule judge adjudicate``: score an evidence
range against a digest-pinned prompt YAML and append a judgment capsule;
record a MANUAL spot-check adjudication of an existing one."""
from __future__ import annotations

from pathlib import Path

from capsule_ledger.cli.main import main
from capsule_ledger.conversation import ConversationSession
from capsule_ledger.guards.signing import LocalSigner
from capsule_ledger.judge.capsules import EVENT_ADJUDICATION, EVENT_JUDGMENT
from capsule_ledger.ledger import LedgerStore

PROMPT_YAML = """
prompt_id: conversation.agreement_reached/1.0.0
label_set: [agreement_reached, no_agreement]
instructions: Did the conversation reach agreement on a remedial action?
"""


def _seed_session(ledger_dir: Path, session_id: str = "sess-cli") -> None:
    signer = LocalSigner(key_id="seed-key", secret=b"seed-secret")
    store = LedgerStore(ledger_dir)
    try:
        sess = ConversationSession(ledger=store, session_id=session_id, operator="op", developer="dev", signer_provider=lambda: signer)
        sess.record_turn(speaker_role="user", content_digest="a" * 64)
        sess.record_turn(speaker_role="assistant", content_digest="b" * 64)
        sess.close()
    finally:
        store.close()


def test_judge_run_static_scorer_appends_a_judgment(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("CAPSULE_MCP_SIGNING_KEY_ID", "cli-key")
    monkeypatch.setenv("CAPSULE_MCP_SIGNING_SECRET", "cli-secret")
    ledger_dir = tmp_path / "ledger"
    _seed_session(ledger_dir)
    prompt_path = tmp_path / "prompt.yaml"
    prompt_path.write_text(PROMPT_YAML)

    rc = main(
        [
            "judge", "run",
            "--ledger", str(ledger_dir),
            "--prompt", str(prompt_path),
            "--session", "sess-cli",
            "--evidence-text", "they agreed to a fix",
            "--scorer", "static",
            "--static-label", "agreement_reached",
            "--static-confidence", "0.87",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "judgment recorded:" in out
    assert "agreement_reached" in out

    store = LedgerStore(ledger_dir)
    try:
        records = [r for r in store.scan() if r.capsule["asg_payload"]["event"] == EVENT_JUDGMENT]
    finally:
        store.close()
    assert len(records) == 1
    detail = records[0].capsule["asg_payload"]["detail"]
    assert detail["label"] == "agreement_reached"
    assert detail["confidence_micros"] == 870_000
    assert len(detail["evidence"]["turn_capsule_ids"]) == 2
    # the conversation session had already closed -- run() auto-chains to it.
    assert "session_digest" in detail["evidence"]
    assert records[0].capsule["chain"]["relation"] == "confirms"


def test_judge_run_explicit_turn_capsule_ids(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("CAPSULE_MCP_SIGNING_KEY_ID", "cli-key")
    monkeypatch.setenv("CAPSULE_MCP_SIGNING_SECRET", "cli-secret")
    ledger_dir = tmp_path / "ledger"
    _seed_session(ledger_dir)
    prompt_path = tmp_path / "prompt.yaml"
    prompt_path.write_text(PROMPT_YAML)

    store = LedgerStore(ledger_dir)
    try:
        turn_ids = [r.capsule_id for r in store.scan() if r.capsule["asg_payload"]["event"] == "conversation_turn"]
    finally:
        store.close()
    assert len(turn_ids) == 2

    rc = main(
        [
            "judge", "run",
            "--ledger", str(ledger_dir),
            "--prompt", str(prompt_path),
            "--session", "sess-cli",
            "--turn-capsule-id", turn_ids[0],
            "--speaker-role", "user",
            "--evidence-text", "just the user's turn",
            "--scorer", "static",
            "--static-label", "no_agreement",
            "--static-confidence", "0.4",
        ]
    )
    assert rc == 0
    store = LedgerStore(ledger_dir)
    try:
        judgment = next(r for r in store.scan() if r.capsule["asg_payload"]["event"] == EVENT_JUDGMENT)
    finally:
        store.close()
    detail = judgment.capsule["asg_payload"]["detail"]
    assert detail["evidence"]["turn_capsule_ids"] == [turn_ids[0]]
    assert detail["target_speaker_role"] == "user"


def test_judge_run_missing_evidence_is_a_usage_error(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("CAPSULE_MCP_SIGNING_KEY_ID", "cli-key")
    monkeypatch.setenv("CAPSULE_MCP_SIGNING_SECRET", "cli-secret")
    ledger_dir = tmp_path / "ledger"
    _seed_session(ledger_dir)
    prompt_path = tmp_path / "prompt.yaml"
    prompt_path.write_text(PROMPT_YAML)

    rc = main(["judge", "run", "--ledger", str(ledger_dir), "--prompt", str(prompt_path), "--session", "sess-cli"])
    assert rc == 1
    assert "evidence-text" in capsys.readouterr().err


def test_judge_run_static_scorer_requires_label_and_confidence(tmp_path, monkeypatch):
    monkeypatch.setenv("CAPSULE_MCP_SIGNING_KEY_ID", "cli-key")
    monkeypatch.setenv("CAPSULE_MCP_SIGNING_SECRET", "cli-secret")
    ledger_dir = tmp_path / "ledger"
    _seed_session(ledger_dir)
    prompt_path = tmp_path / "prompt.yaml"
    prompt_path.write_text(PROMPT_YAML)

    rc = main(
        [
            "judge", "run", "--ledger", str(ledger_dir), "--prompt", str(prompt_path), "--session", "sess-cli",
            "--evidence-text", "x", "--scorer", "static",
        ]
    )
    assert rc == 1


def test_judge_adjudicate_agree(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("CAPSULE_MCP_SIGNING_KEY_ID", "cli-key")
    monkeypatch.setenv("CAPSULE_MCP_SIGNING_SECRET", "cli-secret")
    ledger_dir = tmp_path / "ledger"
    _seed_session(ledger_dir)
    prompt_path = tmp_path / "prompt.yaml"
    prompt_path.write_text(PROMPT_YAML)
    main(
        [
            "judge", "run", "--ledger", str(ledger_dir), "--prompt", str(prompt_path), "--session", "sess-cli",
            "--evidence-text", "ev", "--scorer", "static", "--static-label", "agreement_reached", "--static-confidence", "0.9",
        ]
    )
    capsys.readouterr()

    store = LedgerStore(ledger_dir)
    try:
        judgment_id = next(r.capsule_id for r in store.scan() if r.capsule["asg_payload"]["event"] == EVENT_JUDGMENT)
    finally:
        store.close()

    rc = main(
        [
            "judge", "adjudicate", "--ledger", str(ledger_dir), "--judgment", judgment_id,
            "--label", "agreement_reached", "--agree", "--rationale", "spot-checked",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "adjudication recorded:" in out
    assert "accept" in out

    store = LedgerStore(ledger_dir)
    try:
        adjudications = [r for r in store.scan() if r.capsule["asg_payload"]["event"] == EVENT_ADJUDICATION]
    finally:
        store.close()
    assert len(adjudications) == 1
    assert adjudications[0].capsule["disposition"]["human_disposed"] is True


def test_judge_adjudicate_override_rejects_mismatched_agree(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("CAPSULE_MCP_SIGNING_KEY_ID", "cli-key")
    monkeypatch.setenv("CAPSULE_MCP_SIGNING_SECRET", "cli-secret")
    ledger_dir = tmp_path / "ledger"
    _seed_session(ledger_dir)
    prompt_path = tmp_path / "prompt.yaml"
    prompt_path.write_text(PROMPT_YAML)
    main(
        [
            "judge", "run", "--ledger", str(ledger_dir), "--prompt", str(prompt_path), "--session", "sess-cli",
            "--evidence-text", "ev", "--scorer", "static", "--static-label", "agreement_reached", "--static-confidence", "0.9",
        ]
    )
    capsys.readouterr()
    store = LedgerStore(ledger_dir)
    try:
        judgment_id = next(r.capsule_id for r in store.scan() if r.capsule["asg_payload"]["event"] == EVENT_JUDGMENT)
    finally:
        store.close()

    rc = main(
        [
            "judge", "adjudicate", "--ledger", str(ledger_dir), "--judgment", judgment_id,
            "--label", "no_agreement", "--agree",  # contradiction: agree=True but a different label
        ]
    )
    assert rc == 1
    assert "adjudication_label_mismatch" in capsys.readouterr().err


def test_judge_adjudicate_unknown_capsule_id(tmp_path, monkeypatch):
    monkeypatch.setenv("CAPSULE_MCP_SIGNING_KEY_ID", "cli-key")
    monkeypatch.setenv("CAPSULE_MCP_SIGNING_SECRET", "cli-secret")
    ledger_dir = tmp_path / "ledger"
    _seed_session(ledger_dir)
    rc = main(["judge", "adjudicate", "--ledger", str(ledger_dir), "--judgment", "f" * 64, "--label", "x", "--agree"])
    assert rc == 1


def test_judge_no_subcommand_prints_help(capsys):
    rc = main(["judge"])
    assert rc == 0
    assert "judge" in capsys.readouterr().out
