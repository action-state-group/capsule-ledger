# SPDX-License-Identifier: Apache-2.0
"""Judge prompt definitions: parsing, validation, and the ``prompt_digest``
that pins one exact prompt+label-set to every judgment it produces.

Mirrors ``folds/definition.py``'s own shape exactly (a validated, immutable
dataclass computed from a plain YAML dict, with a ``canonical_dict()`` ->
``prompt_digest()`` pair that reuses ``agent_action_capsule.canonical`` rather
than reimplementing JCS) -- a pack cites a judge prompt by this digest the
same way it cites a fold by its ``definition_digest()``, per the Outcome
Compiler doc's "prompts digest-pinned in the pack" requirement.

The prompt's own free-text ``instructions`` are part of the digest (a
one-character rubric edit must change the digest, so a drifted prompt cannot
silently keep producing judgment capsules that claim the old, audited
wording) but are never interpreted here -- this module only pins and
identifies a prompt; a ``Scorer`` is what actually reads ``instructions`` and
calls a model (``scorer.py``).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from agent_action_capsule.canonical import json_digest

from .errors import (
    DUPLICATE_LABEL,
    EMPTY_LABEL_SET,
    INVALID_PROMPT_ID,
    MALFORMED_PROMPT_DEFINITION,
    JudgeError,
)

__all__ = ["JudgePromptDefinition", "parse_prompt_definition", "PROMPT_ID_RE"]

# prompt_id: same "namespace + semver" shape as fold_id (folds/definition.py's
# FOLD_ID_RE) -- a judge prompt is a versioned, citable artifact exactly like
# a fold definition, not a free-form label.
PROMPT_ID_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*/\d+\.\d+\.\d+$")


@dataclass(frozen=True)
class JudgePromptDefinition:
    prompt_id: str
    label_set: tuple[str, ...]
    instructions: str
    model_id_hint: str | None = None

    def canonical_dict(self) -> dict:
        """The JCS-canonicalizable form of this prompt -- drives ``prompt_digest``."""
        out: dict[str, Any] = {
            "prompt_id": self.prompt_id,
            "label_set": list(self.label_set),
            "instructions": self.instructions,
        }
        if self.model_id_hint is not None:
            out["model_id_hint"] = self.model_id_hint
        return out

    def prompt_digest(self) -> str:
        """SHA-256 over the JCS bytes of the canonical prompt definition."""
        return json_digest(self.canonical_dict())


def parse_prompt_definition(data: Any) -> JudgePromptDefinition:
    """Validate a plain dict (as loaded from YAML) into a
    ``JudgePromptDefinition``."""
    if not isinstance(data, dict):
        raise JudgeError(MALFORMED_PROMPT_DEFINITION, "prompt definition must be a mapping")

    prompt_id = data.get("prompt_id")
    if not isinstance(prompt_id, str) or not PROMPT_ID_RE.match(prompt_id):
        raise JudgeError(
            INVALID_PROMPT_ID,
            f"prompt_id {prompt_id!r} must match '<namespace>[.<namespace>...]/<major>.<minor>.<patch>' "
            "(e.g. 'conversation.agreement_reached/1.0.0')",
        )

    raw_label_set = data.get("label_set")
    if not isinstance(raw_label_set, list) or not raw_label_set:
        raise JudgeError(EMPTY_LABEL_SET, "label_set must be a non-empty list of strings")
    label_set: list[str] = []
    seen: set[str] = set()
    for label in raw_label_set:
        if not isinstance(label, str) or not label:
            raise JudgeError(MALFORMED_PROMPT_DEFINITION, f"label_set entries must be non-empty strings, got {label!r}")
        if label in seen:
            raise JudgeError(DUPLICATE_LABEL, f"label {label!r} declared more than once in label_set")
        seen.add(label)
        label_set.append(label)

    instructions = data.get("instructions")
    if not isinstance(instructions, str) or not instructions.strip():
        raise JudgeError(MALFORMED_PROMPT_DEFINITION, "instructions is required and must be a non-empty string")

    model_id_hint = data.get("model_id_hint")
    if model_id_hint is not None and not isinstance(model_id_hint, str):
        raise JudgeError(MALFORMED_PROMPT_DEFINITION, "model_id_hint must be a string when given")

    return JudgePromptDefinition(
        prompt_id=prompt_id,
        label_set=tuple(label_set),
        instructions=instructions,
        model_id_hint=model_id_hint,
    )
