# SPDX-License-Identifier: Apache-2.0
"""Tests for judge prompt definitions: parsing, validation, and the
``prompt_digest`` that pins one exact prompt+label-set to every judgment it
produces."""
from __future__ import annotations

import pytest

from capsule_ledger.judge.errors import (
    DUPLICATE_LABEL,
    EMPTY_LABEL_SET,
    INVALID_PROMPT_ID,
    MALFORMED_PROMPT_DEFINITION,
    JudgeError,
)
from capsule_ledger.judge.loader import load_prompt_file, load_prompt_text
from capsule_ledger.judge.prompt import JudgePromptDefinition, parse_prompt_definition

VALID = {
    "prompt_id": "conversation.agreement_reached/1.0.0",
    "label_set": ["agreement_reached", "no_agreement"],
    "instructions": "Did the conversation reach agreement on a remedial action?",
}


def test_parses_a_valid_definition():
    prompt = parse_prompt_definition(VALID)
    assert prompt.prompt_id == "conversation.agreement_reached/1.0.0"
    assert prompt.label_set == ("agreement_reached", "no_agreement")
    assert prompt.model_id_hint is None


def test_optional_model_id_hint_round_trips():
    prompt = parse_prompt_definition({**VALID, "model_id_hint": "gpt-4o-mini"})
    assert prompt.model_id_hint == "gpt-4o-mini"
    assert prompt.canonical_dict()["model_id_hint"] == "gpt-4o-mini"


@pytest.mark.parametrize("bad_id", ["not-versioned", "conversation/agreement_reached", "Conversation.x/1.0.0", ""])
def test_invalid_prompt_id_rejected(bad_id):
    with pytest.raises(JudgeError) as exc_info:
        parse_prompt_definition({**VALID, "prompt_id": bad_id})
    assert exc_info.value.reason == INVALID_PROMPT_ID


def test_empty_label_set_rejected():
    with pytest.raises(JudgeError) as exc_info:
        parse_prompt_definition({**VALID, "label_set": []})
    assert exc_info.value.reason == EMPTY_LABEL_SET


def test_duplicate_label_rejected():
    with pytest.raises(JudgeError) as exc_info:
        parse_prompt_definition({**VALID, "label_set": ["x", "x"]})
    assert exc_info.value.reason == DUPLICATE_LABEL


def test_missing_instructions_rejected():
    data = dict(VALID)
    del data["instructions"]
    with pytest.raises(JudgeError) as exc_info:
        parse_prompt_definition(data)
    assert exc_info.value.reason == MALFORMED_PROMPT_DEFINITION


def test_not_a_mapping_rejected():
    with pytest.raises(JudgeError) as exc_info:
        parse_prompt_definition(["not", "a", "mapping"])
    assert exc_info.value.reason == MALFORMED_PROMPT_DEFINITION


# -- digest pinning ------------------------------------------------------


def test_prompt_digest_is_deterministic():
    p1 = parse_prompt_definition(VALID)
    p2 = parse_prompt_definition(dict(VALID))
    assert p1.prompt_digest() == p2.prompt_digest()


def test_prompt_digest_changes_with_instructions():
    p1 = parse_prompt_definition(VALID)
    p2 = parse_prompt_definition({**VALID, "instructions": VALID["instructions"] + " "})
    assert p1.prompt_digest() != p2.prompt_digest()


def test_prompt_digest_changes_with_label_set():
    p1 = parse_prompt_definition(VALID)
    p2 = parse_prompt_definition({**VALID, "label_set": ["agreement_reached", "no_agreement", "escalated"]})
    assert p1.prompt_digest() != p2.prompt_digest()


def test_prompt_digest_ignores_key_order_in_source_yaml():
    # JCS canonicalization sorts keys -- a reordered-but-otherwise-identical
    # dict must digest identically (fixture-hygiene discipline: a prompt's
    # identity is its content, not its YAML author's key order).
    reordered = {"instructions": VALID["instructions"], "label_set": VALID["label_set"], "prompt_id": VALID["prompt_id"]}
    assert parse_prompt_definition(VALID).prompt_digest() == parse_prompt_definition(reordered).prompt_digest()


# -- YAML front door ------------------------------------------------------


def test_load_prompt_text_round_trips_yaml():
    text = """
    prompt_id: conversation.agreement_reached/1.0.0
    label_set:
      - agreement_reached
      - no_agreement
    instructions: "Did the conversation reach agreement on a remedial action?"
    """
    prompt = load_prompt_text(text)
    assert prompt == parse_prompt_definition(VALID)


def test_load_prompt_text_rejects_invalid_yaml():
    with pytest.raises(JudgeError) as exc_info:
        load_prompt_text("prompt_id: [unterminated")
    assert exc_info.value.reason == MALFORMED_PROMPT_DEFINITION


def test_load_prompt_text_rejects_empty_document():
    with pytest.raises(JudgeError) as exc_info:
        load_prompt_text("")
    assert exc_info.value.reason == MALFORMED_PROMPT_DEFINITION


def test_load_prompt_file(tmp_path):
    path = tmp_path / "prompt.yaml"
    path.write_text(
        "prompt_id: conversation.agreement_reached/1.0.0\n"
        "label_set: [agreement_reached, no_agreement]\n"
        "instructions: Did they agree?\n"
    )
    prompt = load_prompt_file(path)
    assert prompt.prompt_id == "conversation.agreement_reached/1.0.0"


def test_prompt_definition_is_frozen():
    prompt = JudgePromptDefinition(prompt_id="a.b/1.0.0", label_set=("x",), instructions="i")
    with pytest.raises(AttributeError):
        prompt.prompt_id = "changed"  # type: ignore[misc]
