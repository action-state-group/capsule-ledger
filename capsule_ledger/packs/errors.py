# SPDX-License-Identifier: Apache-2.0
"""Named-reason errors for pack definitions (mirrors ``folds/errors.py`` /
``guards/wickets/errors.py`` / ``policy/errors.py``).

A dev's AI coding tool is the primary author of ``pack.yaml`` files (starter-
packs plan: "AI-coded by design"), so every message here follows the same
rule that made those three modules' errors actionable: name the field, say
what was expected, show a correct example inline. A reason code alone is
for tests and tooling; the message is for whoever (human or model) has to
fix the file.
"""
from __future__ import annotations

PACK_NOT_FOUND = "pack_not_found"
MALFORMED_PACK = "malformed_pack"
INVALID_PACK_ID = "invalid_pack_id_namespace"
MISSING_REQUIRED_FIELD = "missing_required_field"
OBLIGATION_CHECK_NOT_DECLARED = "obligation_check_not_declared"
DUPLICATE_OBLIGATION_ID = "duplicate_obligation_id"
INVALID_ACTION_SEMANTIC = "invalid_action_semantic"
UNKNOWN_NORMALIZED_FIELD = "unknown_normalized_field"
UNKNOWN_ACTION_CLASS = "unknown_action_class"
DUPLICATE_ACTION_TYPE = "duplicate_action_type"
INVALID_CONSTRAINT = "invalid_constraint"
DUPLICATE_CONSTRAINT_WICKET_ID = "duplicate_constraint_wicket_id"
FOLD_FILE_NOT_FOUND = "fold_file_not_found"
INVALID_FOLD_REF = "invalid_fold_ref"
INVALID_HOLDS_INTEGRATION = "invalid_holds_integration"
INVALID_FIXTURES = "invalid_fixtures"
FLOAT_IN_PACK_DIGEST = "float_in_pack_digest"
UNSAFE_INTEGER_IN_PACK_DIGEST = "unsafe_integer_in_pack_digest"


class PackDefinitionError(ValueError):
    """A pack definition (``pack.yaml`` plus its referenced files) fails to
    parse or validate. Carries a stable reason code, same discipline as
    ``FoldDefinitionError`` / ``WicketDefinitionError`` / ``PolicyManifestError``."""

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(f"{reason}: {message}")
