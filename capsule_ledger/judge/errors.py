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

# Judge-pin (full-pin) build-time reasons.
RATE_OUT_OF_RANGE = "rate_out_of_range"
SAMPLING_PARAM_NOT_DIGEST_SAFE = "sampling_param_not_digest_safe"
EXTERNAL_PROOF_REF_MALFORMED = "external_proof_ref_malformed"

# Adjudication-build-time reasons.
JUDGMENT_NOT_FOUND = "judgment_not_found"
ADJUDICATION_LABEL_MISMATCH = "adjudication_label_mismatch"

# Drift-check build-time reasons.
JUDGE_PIN_MISSING = "judge_pin_missing"

# Scorer reasons.
SCORER_LABEL_NOT_IN_LABEL_SET = "scorer_label_not_in_label_set"
SCORER_DEPENDENCY_MISSING = "scorer_dependency_missing"

# Outcomes -> judge-prompt compiler reasons ([outcomes-to-judgeprompt-compiler-t3]).
REFUSED_OUTCOME_NO_JUDGE_PROMPT = "refused_outcome_no_judge_prompt"

# Evidence-completeness (insufficient_evidence, design §11) build-time reasons.
MISSING_EVIDENCE_LABEL_REQUIRED = "missing_evidence_label_required"
MISSING_EVIDENCE_LABEL_NOT_ALLOWED = "missing_evidence_label_not_allowed"


class JudgeError(ValueError):
    """A judge-harness object fails to parse, validate, or build. Carries a
    stable reason code."""

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(f"{reason}: {message}")
