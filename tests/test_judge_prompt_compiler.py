# SPDX-License-Identifier: Apache-2.0
"""Tests for the outcomes -> judge-prompt compiler
([outcomes-to-judgeprompt-compiler-t3]): a confirmed pack outcome's
``statement`` + ``evidence_rule``, framed by a shared ``PackContextBlock``,
compiles into a digest-pinned ``JudgePromptDefinition``."""
from __future__ import annotations

import pytest

from capsule_ledger.judge.errors import (
    DUPLICATE_LABEL,
    EMPTY_LABEL_SET,
    REFUSED_OUTCOME_NO_JUDGE_PROMPT,
    JudgeError,
)
from capsule_ledger.judge.prompt_compiler import (
    DEFAULT_LABEL_SET,
    PackContextBlock,
    compile_judge_prompt,
)
from capsule_ledger.packs.schema import Outcome

FRAMING = (
    "This pack governs a read-only investigation agent: it may query and read "
    "customer records but must never write, modify, or delete one."
)


def _outcome(**overrides) -> Outcome:
    base = dict(
        id="A1",
        statement="Choice, not ultimatum: the agent presented more than one viable path to resolution.",
        evidence_rule="assistant turn matches option-shaped language: an offer of >=2 named alternatives.",
        forward_verdict="WITH-INSTRUMENTATION",
        backward_verdict="WITH-INSTRUMENTATION",
    )
    base.update(overrides)
    return Outcome(**base)


def _pack_context(**overrides) -> PackContextBlock:
    base = dict(pack_id="asg/airline-engagement/1.0.0", framing=FRAMING)
    base.update(overrides)
    return PackContextBlock(**base)


# -- compiles from a term -------------------------------------------------


def test_prompt_compiles_from_a_term():
    outcome = _outcome()
    prompt = compile_judge_prompt(outcome, _pack_context())

    assert prompt.prompt_id == "a1/1.0.0"
    assert prompt.label_set == DEFAULT_LABEL_SET
    assert outcome.statement in prompt.instructions
    assert outcome.evidence_rule in prompt.instructions
    assert FRAMING in prompt.instructions
    # A prompt compiled straight from a term is a real, digest-pinned
    # JudgePromptDefinition -- not a bare statement.
    assert prompt.prompt_digest()


def test_prompt_id_namespace_is_lowercased_from_the_outcome_id():
    # Real pack outcome ids are upper-cased ("A1", "A3a", ...) -- the
    # compiler must not hand PROMPT_ID_RE a namespace it will reject.
    prompt = compile_judge_prompt(_outcome(id="A3a"), _pack_context())
    assert prompt.prompt_id == "a3a/1.0.0"


def test_prompt_version_is_configurable():
    prompt = compile_judge_prompt(_outcome(), _pack_context(), version="2.1.0")
    assert prompt.prompt_id == "a1/2.1.0"


def test_two_outcomes_in_the_same_pack_share_the_pack_context_framing():
    pack_context = _pack_context()
    p1 = compile_judge_prompt(_outcome(id="A1"), pack_context)
    p2 = compile_judge_prompt(_outcome(id="A6", statement="Handled, not offloaded.", evidence_rule="no transfer_to_human_agents call."), pack_context)
    assert FRAMING in p1.instructions
    assert FRAMING in p2.instructions
    assert p1.prompt_digest() != p2.prompt_digest()


def test_different_evidence_rule_changes_the_digest():
    p1 = compile_judge_prompt(_outcome(), _pack_context())
    p2 = compile_judge_prompt(_outcome(evidence_rule="a different evidence rule entirely"), _pack_context())
    assert p1.prompt_digest() != p2.prompt_digest()


def test_different_pack_context_framing_changes_the_digest():
    p1 = compile_judge_prompt(_outcome(), _pack_context())
    p2 = compile_judge_prompt(_outcome(), _pack_context(framing="A completely different domain framing block."))
    assert p1.prompt_digest() != p2.prompt_digest()


def test_same_term_compiles_to_the_same_prompt_digest_twice():
    # Determinism invariant: compiling the same outcome+pack-context twice,
    # from fresh objects each time (not the same instance re-used), must
    # yield the same prompt_digest -- the digest is a pure function of the
    # term's content, not of object identity or compile order.
    p1 = compile_judge_prompt(_outcome(), _pack_context())
    p2 = compile_judge_prompt(_outcome(), _pack_context())
    assert p1.prompt_digest() == p2.prompt_digest()


def test_custom_label_set_and_model_id_hint_round_trip():
    prompt = compile_judge_prompt(
        _outcome(), _pack_context(), label_set=("meets", "does_not_meet"), model_id_hint="gemini-2.5-flash"
    )
    assert prompt.label_set == ("meets", "does_not_meet")
    assert prompt.model_id_hint == "gemini-2.5-flash"


# -- refuses a REFUSED outcome --------------------------------------------


def test_refuses_a_refused_outcome():
    outcome = _outcome(
        evidence_rule="n/a -- unbounded goal, refused by design",
        forward_verdict="REFUSED",
        backward_verdict="REFUSED",
    )
    with pytest.raises(JudgeError) as exc_info:
        compile_judge_prompt(outcome, _pack_context())
    assert exc_info.value.reason == REFUSED_OUTCOME_NO_JUDGE_PROMPT


# -- pack context validation -----------------------------------------------


def test_pack_context_requires_non_empty_framing():
    with pytest.raises(ValueError):
        PackContextBlock(pack_id="asg/x/1.0.0", framing="   ")


def test_pack_context_requires_non_empty_pack_id():
    with pytest.raises(ValueError):
        PackContextBlock(pack_id="", framing=FRAMING)


# -- label set guards (constructing a JudgePromptDefinition directly skips
#    parse_prompt_definition's own checks, so the compiler re-asserts them) --


def test_rejects_empty_label_set():
    with pytest.raises(JudgeError) as exc_info:
        compile_judge_prompt(_outcome(), _pack_context(), label_set=())
    assert exc_info.value.reason == EMPTY_LABEL_SET


def test_rejects_duplicate_labels():
    with pytest.raises(JudgeError) as exc_info:
        compile_judge_prompt(_outcome(), _pack_context(), label_set=("pass", "pass"))
    assert exc_info.value.reason == DUPLICATE_LABEL
