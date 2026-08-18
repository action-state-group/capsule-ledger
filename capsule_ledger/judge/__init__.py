# SPDX-License-Identifier: Apache-2.0
"""B3-minimal: the generic model-assisted recorded-claims judge harness.

Scope: a swappable ``Scorer``
shell with a DeepEval-backed default, prompt digest-pinning, judgment
capsules (with optional per-speaker-role targeting against the B5
conversation profile), and MANUAL spot-check adjudication. 
"""
from __future__ import annotations

from .capsules import (
    EVENT_ADJUDICATION,
    EVENT_JUDGMENT,
    EVENT_PROMPT_ACTIVATED,
    build_adjudication_capsule,
    build_judge_prompt_activation_capsule,
    build_judgment_capsule,
    find_adjudications_for_judgment,
    find_judgments_for_session,
    find_latest_prompt_activation,
)
from .errors import JudgeError
from .harness import JudgeHarness
from .loader import load_prompt_file, load_prompt_text
from .prompt import JudgePromptDefinition, parse_prompt_definition
from .scorer import JudgeEvidence, Scorer, ScoreResult

__all__ = [
    "EVENT_JUDGMENT",
    "EVENT_ADJUDICATION",
    "EVENT_PROMPT_ACTIVATED",
    "JudgeError",
    "JudgeEvidence",
    "JudgeHarness",
    "JudgePromptDefinition",
    "ScoreResult",
    "Scorer",
    "build_adjudication_capsule",
    "build_judge_prompt_activation_capsule",
    "build_judgment_capsule",
    "find_adjudications_for_judgment",
    "find_judgments_for_session",
    "find_latest_prompt_activation",
    "load_prompt_file",
    "load_prompt_text",
    "parse_prompt_definition",
]
