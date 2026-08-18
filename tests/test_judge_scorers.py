# SPDX-License-Identifier: Apache-2.0
"""Tests for the ``Scorer`` seam: ``StaticScorer`` (the deterministic, no-
network reference implementation) and ``DeepEvalScorer`` (the default, BYOM
implementation -- ``deepeval`` is an optional dependency, so its wiring
tests only run when it's actually installed, and the "not installed" path
is exercised unconditionally since that's this repo's own default state).
"""
from __future__ import annotations

import pytest

from capsule_ledger.judge.errors import SCORER_DEPENDENCY_MISSING, SCORER_LABEL_NOT_IN_LABEL_SET, JudgeError
from capsule_ledger.judge.prompt import JudgePromptDefinition
from capsule_ledger.judge.scorer import JudgeEvidence, ScoreResult
from capsule_ledger.judge.scorers.static import StaticScorer

PROMPT = JudgePromptDefinition(prompt_id="a.b/1.0.0", label_set=("positive", "negative"), instructions="rubric")


def _evidence(text="ev"):
    return JudgeEvidence(session_id="s", turn_capsule_ids=("a" * 64,), evidence_text=text)


# -- StaticScorer -----------------------------------------------------------


def test_static_scorer_returns_scripted_response():
    scorer = StaticScorer(responses={"good conversation": ("positive", 0.75)})
    result = scorer.score(evidence=_evidence("good conversation"), prompt=PROMPT)
    assert result == ScoreResult(label="positive", confidence=0.75, model_id="static-scorer/deterministic")


def test_static_scorer_uses_default_when_unscripted():
    scorer = StaticScorer(default=("negative", 0.5))
    result = scorer.score(evidence=_evidence("anything at all"), prompt=PROMPT)
    assert result.label == "negative"
    assert result.confidence == 0.5


def test_static_scorer_raises_on_unscripted_evidence_without_default():
    scorer = StaticScorer(responses={"only this": ("positive", 0.9)})
    with pytest.raises(JudgeError) as exc_info:
        scorer.score(evidence=_evidence("something else"), prompt=PROMPT)
    assert exc_info.value.reason == SCORER_LABEL_NOT_IN_LABEL_SET


def test_static_scorer_rejects_a_scripted_label_outside_the_prompts_label_set():
    scorer = StaticScorer(responses={"ev": ("neutral", 0.5)})  # "neutral" not in PROMPT.label_set
    with pytest.raises(JudgeError) as exc_info:
        scorer.score(evidence=_evidence(), prompt=PROMPT)
    assert exc_info.value.reason == SCORER_LABEL_NOT_IN_LABEL_SET


def test_static_scorer_is_deterministic():
    scorer = StaticScorer(responses={"ev": ("positive", 0.9)})
    r1 = scorer.score(evidence=_evidence(), prompt=PROMPT)
    r2 = scorer.score(evidence=_evidence(), prompt=PROMPT)
    assert r1 == r2


def test_static_scorer_satisfies_the_scorer_protocol():
    from capsule_ledger.judge.scorer import Scorer

    assert isinstance(StaticScorer(), Scorer)


# -- DeepEvalScorer -----------------------------------------------------------


def test_deepeval_scorer_missing_dependency_raises_a_named_reason():
    if _deepeval_installed():
        pytest.skip("deepeval is installed in this environment -- the not-installed path isn't reachable here")
    from capsule_ledger.judge.scorers.deepeval_scorer import DeepEvalScorer

    with pytest.raises(JudgeError) as exc_info:
        DeepEvalScorer()
    assert exc_info.value.reason == SCORER_DEPENDENCY_MISSING
    assert "capsule-ledger[judge]" in str(exc_info.value)


def _deepeval_installed() -> bool:
    try:
        import deepeval  # noqa: F401
    except ImportError:
        return False
    return True


@pytest.mark.skipif(not _deepeval_installed(), reason="deepeval is an optional dependency (pip install capsule-ledger[judge])")
def test_deepeval_scorer_wiring_picks_the_highest_scoring_label(monkeypatch):
    # No real model call: GEval.measure is patched so this proves the
    # wiring (construction, per-label GEval instances, argmax selection,
    # ScoreResult mapping) against the REAL installed deepeval API without
    # needing network access or an API key at call time.
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-construction-only")
    from capsule_ledger.judge.scorers.deepeval_scorer import DeepEvalScorer

    prompt = JudgePromptDefinition(
        prompt_id="conversation.sentiment/1.0.0", label_set=("positive", "neutral", "negative"), instructions="Judge sentiment."
    )
    evidence = JudgeEvidence(session_id="s1", turn_capsule_ids=("a" * 64,), evidence_text="This was great, thank you!")
    scorer = DeepEvalScorer(model="gpt-4o-mini")

    calls = []

    def fake_measure(self, test_case, **kwargs):
        calls.append(self.name)
        self.score = 0.9 if self.name.endswith("::positive") else 0.2
        self.reason = f"reason for {self.name}"
        self.evaluation_model = "gpt-4o-mini"
        return self.score

    monkeypatch.setattr(scorer._GEval, "measure", fake_measure)
    result = scorer.score(evidence=evidence, prompt=prompt)

    assert len(calls) == 3  # one GEval instance per candidate label
    assert result.label == "positive"
    assert result.confidence == pytest.approx(0.9)
    assert result.model_id == "gpt-4o-mini"
    assert result.rationale == "reason for conversation.sentiment/1.0.0::positive"
