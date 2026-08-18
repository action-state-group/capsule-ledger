# SPDX-License-Identifier: Apache-2.0
"""Tests for ``JudgeHarness``: the orchestration seam tying a digest-pinned
prompt, a ``Scorer``, and evidence together into a signed, appended
judgment capsule, plus the human-adjudication call.
"""
from __future__ import annotations

import pytest

from capsule_ledger.conversation import ConversationSession
from capsule_ledger.guards.signing import SigningKeyUnavailable
from capsule_ledger.judge.capsules import EVENT_ADJUDICATION, EVENT_JUDGMENT
from capsule_ledger.judge.errors import SCORER_LABEL_NOT_IN_LABEL_SET, JudgeError
from capsule_ledger.judge.harness import JudgeHarness
from capsule_ledger.judge.prompt import JudgePromptDefinition
from capsule_ledger.judge.scorer import JudgeEvidence
from capsule_ledger.judge.scorers.static import StaticScorer

OPERATOR = "acme-support"
DEVELOPER = "judge-harness@v1"

PROMPT = JudgePromptDefinition(
    prompt_id="conversation.agreement_reached/1.0.0",
    label_set=("agreement_reached", "no_agreement"),
    instructions="Did the conversation reach agreement?",
)


def _harness(store, signer, scorer=None):
    return JudgeHarness(
        ledger=store,
        prompt=PROMPT,
        scorer=scorer or StaticScorer(default=("agreement_reached", 0.9)),
        operator=OPERATOR,
        developer=DEVELOPER,
        signer_provider=lambda: signer,
    )


def test_run_appends_a_real_verifiable_judgment(store, signer):
    harness = _harness(store, signer)
    evidence = JudgeEvidence(session_id="sess-1", turn_capsule_ids=("a" * 64,), evidence_text="ev")
    record = harness.run(evidence=evidence)
    assert store.verify(record.capsule_id).ok
    assert record.capsule["asg_payload"]["event"] == EVENT_JUDGMENT
    assert record.capsule["asg_payload"]["detail"]["label"] == "agreement_reached"


def test_run_end_to_end_against_a_real_conversation_session(store, signer):
    sess = ConversationSession(ledger=store, session_id="sess-real", operator=OPERATOR, developer=DEVELOPER, signer_provider=lambda: signer)
    t0 = sess.record_turn(speaker_role="user", content_digest="a" * 64)
    t1 = sess.record_turn(speaker_role="assistant", content_digest="b" * 64)
    close = sess.close()

    harness = _harness(store, signer)
    evidence = JudgeEvidence(session_id="sess-real", turn_capsule_ids=(t0.capsule_id, t1.capsule_id), evidence_text="ev")
    record = harness.run(
        evidence=evidence,
        session_digest=close.capsule["asg_payload"]["detail"]["session_digest"],
        chain_parent=close.capsule_id,
    )
    assert store.verify(record.capsule_id).ok
    assert record.capsule["chain"] == {"parent_capsule_id": close.capsule_id, "relation": "confirms"}


def test_run_propagates_scorer_errors_without_appending_anything(store, signer):
    scorer = StaticScorer(responses={"scripted": ("no_such_label", 0.5)})
    harness = _harness(store, signer, scorer=scorer)
    evidence = JudgeEvidence(session_id="sess-1", turn_capsule_ids=("a" * 64,), evidence_text="scripted")
    with pytest.raises(JudgeError) as exc_info:
        harness.run(evidence=evidence)
    assert exc_info.value.reason == SCORER_LABEL_NOT_IN_LABEL_SET
    assert list(store.scan()) == []


def test_run_no_unsigned_window_signing_failure_propagates_not_silently_recorded(store):
    def _unavailable():
        raise SigningKeyUnavailable("key rotated out")

    harness = JudgeHarness(
        ledger=store, prompt=PROMPT, scorer=StaticScorer(default=("agreement_reached", 0.9)),
        operator=OPERATOR, developer=DEVELOPER, signer_provider=_unavailable,
    )
    evidence = JudgeEvidence(session_id="sess-1", turn_capsule_ids=("a" * 64,), evidence_text="ev")
    with pytest.raises(SigningKeyUnavailable):
        harness.run(evidence=evidence)
    assert list(store.scan()) == []


def test_adjudicate_appends_a_real_verifiable_adjudication(store, signer):
    harness = _harness(store, signer)
    evidence = JudgeEvidence(session_id="sess-1", turn_capsule_ids=("a" * 64,), evidence_text="ev")
    judgment_record = harness.run(evidence=evidence)

    adjudication_record = harness.adjudicate(
        judgment=judgment_record.capsule, label="agreement_reached", agrees_with_judge=True, rationale="checked"
    )
    assert store.verify(adjudication_record.capsule_id).ok
    assert adjudication_record.capsule["asg_payload"]["event"] == EVENT_ADJUDICATION
    assert adjudication_record.capsule["chain"]["parent_capsule_id"] == judgment_record.capsule_id


def test_adjudicate_no_unsigned_window(store, signer):
    harness = _harness(store, signer)
    evidence = JudgeEvidence(session_id="sess-1", turn_capsule_ids=("a" * 64,), evidence_text="ev")
    judgment_record = harness.run(evidence=evidence)

    def _unavailable():
        raise SigningKeyUnavailable("key rotated out")

    flaky_harness = JudgeHarness(
        ledger=store, prompt=PROMPT, scorer=StaticScorer(default=("agreement_reached", 0.9)),
        operator=OPERATOR, developer=DEVELOPER, signer_provider=_unavailable,
    )
    with pytest.raises(SigningKeyUnavailable):
        flaky_harness.adjudicate(judgment=judgment_record.capsule, label="agreement_reached", agrees_with_judge=True)
    assert len(list(store.scan())) == 1  # only the judgment from harness.run() above; the adjudication never appended


# -- judge never in the enforcement path (structural) ------------------------


def _imports_guard_engine(tree) -> bool:
    import ast

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names = [alias.name for alias in node.names]
            if module.endswith("guards.engine") or ".guards.engine" in module:
                return True
            if module.endswith("guards") and "engine" in names:
                return True
            if "GuardEngine" in names:
                return True
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if "guards.engine" in alias.name:
                    return True
    return False


def test_judge_package_never_imports_guard_engine():
    import ast
    from pathlib import Path

    import capsule_ledger.judge as judge_pkg

    judge_dir = Path(judge_pkg.__file__).parent
    for path in judge_dir.rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        assert not _imports_guard_engine(tree), f"{path} imports guards.engine/GuardEngine -- judge must never be wired into the enforcement path"
