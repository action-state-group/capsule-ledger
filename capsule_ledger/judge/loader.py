# SPDX-License-Identifier: Apache-2.0
"""YAML front door for judge prompt definitions: YAML text/file -> validated
``JudgePromptDefinition`` (mirrors ``folds/loader.py`` exactly)."""
from __future__ import annotations

from pathlib import Path

import yaml

from .errors import MALFORMED_PROMPT_DEFINITION, JudgeError
from .prompt import JudgePromptDefinition, parse_prompt_definition

__all__ = ["load_prompt_text", "load_prompt_file"]


def load_prompt_text(text: str) -> JudgePromptDefinition:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise JudgeError(MALFORMED_PROMPT_DEFINITION, f"invalid YAML: {exc}") from exc
    if data is None:
        raise JudgeError(MALFORMED_PROMPT_DEFINITION, "empty prompt definition document")
    return parse_prompt_definition(data)


def load_prompt_file(path: str | Path) -> JudgePromptDefinition:
    return load_prompt_text(Path(path).read_text())
