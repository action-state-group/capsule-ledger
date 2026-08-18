# SPDX-License-Identifier: Apache-2.0
"""Named-reason errors for the judge harness (mirrors ``folds/errors.py`` /
``holds/errors.py`` — every rejection carries a stable ``reason`` code so a
test can pin the reason string, not just "it raised something")."""
from __future__ import annotations

# Prompt-definition (parse/validate) reasons.
MALFORMED_PROMPT_DEFINITION = "malformed_prompt_definition"
INVALID_PROMPT_ID = "invalid_prompt_id_namespace"
EMPTY_LABEL_SET = "empty_label_set"
DUPLICATE_LABEL = "duplicate_label"

# Judgment-build-time reasons.
LABEL_NOT_IN_LABEL_SET = "label_not_in_label_set"
CONFIDENCE_OUT_OF_RANGE = "confidence_out_of_range"
INVALID_SPEAKER_ROLE_TARGET = "invalid_speaker_role_target"
EMPTY_EVIDENCE_RANGE = "empty_evidence_range"

# Adjudication-build-time reasons.
JUDGMENT_NOT_FOUND = "judgment_not_found"
ADJUDICATION_LABEL_MISMATCH = "adjudication_label_mismatch"

# Scorer reasons.
SCORER_LABEL_NOT_IN_LABEL_SET = "scorer_label_not_in_label_set"
SCORER_DEPENDENCY_MISSING = "scorer_dependency_missing"


class JudgeError(ValueError):
    """A judge-harness object fails to parse, validate, or build. Carries a
    stable reason code."""

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(f"{reason}: {message}")
