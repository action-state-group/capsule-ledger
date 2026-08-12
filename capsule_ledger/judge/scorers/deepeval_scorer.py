# SPDX-License-Identifier: Apache-2.0
"""``DeepEvalScorer``: the default (BYOM) ``Scorer`` -- a thin wrapper over
DeepEval's G-Eval metric (``deepeval.metrics.GEval``), per the outcomes-to-
actions design doc §2 ("PRIMARY scorer candidate -- rubric->label with
confidence, exactly the judge's inner loop").

``deepeval`` is an OPTIONAL dependency (``pip install capsule-ledger[judge]``)
-- imported lazily here, never at module import time, so the rest of the
judge harness (prompt digest-pinning, judgment/adjudication capsules) has no
hard dependency on it and stays importable/testable without it installed
(``scorers/static.py`` covers tests and demos that need no model call at all).

G-Eval itself is a scalar quality/pass-fail metric (one criteria -> one
score in [0, 1]), not a native multi-label classifier. This wrapper runs one
GEval instance PER label in the prompt's ``label_set`` -- "does the evidence
support this label, per the following rubric?" -- and picks the highest-
scoring label, using that label's own score as the confidence. This is a
real, callable mapping (verified directly against the installed
``deepeval`` package's constructor/`.measure()` signatures), not a
speculative one; it costs one model call per candidate label, a known,
documented limitation of staying thin rather than hand-rolling a custom
multi-class rubric prompt.
"""
from __future__ import annotations

from ..errors import SCORER_DEPENDENCY_MISSING, SCORER_LABEL_NOT_IN_LABEL_SET, JudgeError
from ..prompt import JudgePromptDefinition
from ..scorer import JudgeEvidence, ScoreResult

__all__ = ["DeepEvalScorer"]


class DeepEvalScorer:
    def __init__(self, *, model: str | None = None):
        try:
            from deepeval.metrics import GEval
            from deepeval.test_case import LLMTestCase, SingleTurnParams
        except ImportError as exc:
            raise JudgeError(
                SCORER_DEPENDENCY_MISSING,
                "DeepEvalScorer requires the optional 'deepeval' package -- "
                "install with `pip install capsule-ledger[judge]`",
            ) from exc
        self._GEval = GEval
        self._LLMTestCase = LLMTestCase
        self._eval_params = [SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT]
        self._model = model

    def score(self, *, evidence: JudgeEvidence, prompt: JudgePromptDefinition) -> ScoreResult:
        test_case = self._LLMTestCase(input=prompt.instructions, actual_output=evidence.evidence_text)

        best_label: str | None = None
        best_score: float = -1.0
        best_metric = None
        for label in prompt.label_set:
            metric = self._GEval(
                name=f"{prompt.prompt_id}::{label}",
                criteria=(
                    f"{prompt.instructions}\n\n"
                    f"Given the evidence above, does it support the label {label!r}? "
                    "Score close to 1.0 if it clearly does, close to 0.0 if it clearly does not."
                ),
                evaluation_params=self._eval_params,
                model=self._model,
            )
            metric.measure(test_case)
            if metric.score is not None and metric.score > best_score:
                best_score, best_label, best_metric = metric.score, label, metric

        if best_label is None:
            raise JudgeError(
                SCORER_LABEL_NOT_IN_LABEL_SET,
                f"DeepEvalScorer produced no usable score for any label in {sorted(prompt.label_set)}",
            )

        model_id = self._model or getattr(best_metric, "evaluation_model", None) or "deepeval/g-eval-default"
        return ScoreResult(
            label=best_label,
            confidence=float(best_score),
            model_id=str(model_id),
            rationale=getattr(best_metric, "reason", None),
        )
