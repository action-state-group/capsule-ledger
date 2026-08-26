# SPDX-License-Identifier: Apache-2.0
"""Judge epochs as ``epoch_opens`` records (terms-to-report design §4 / §8
build item 3). Load-bearing properties, each with a named test:

1. ``build_epoch_open_capsule`` reuses the registered ``epoch_opens`` chain
   relation, chains to the previous judge epoch (never a policy-manifest
   activation, even though both share the relation label), and the first
   epoch in a ledger cites the genesis sentinel.
2. ``pin_set_for_terms`` derives pins straight from compiled terms -- never
   a second, hand-typed description that could drift.
3. ``same_family_epoch_pairs`` is computable from the registry alone (no
   verdict rows needed) and is symmetric/never self-pairs an epoch.
"""
from __future__ import annotations

import pytest
from agent_action_capsule import compute_capsule_id

from capsule_ledger.compiler.compile import CompilerError, Declaration
from capsule_ledger.compiler.epoch_registry import (
    EVENT_EPOCH_OPEN,
    GENESIS_PARENT,
    EpochOpen,
    EpochPin,
    build_epoch_open_capsule,
    epoch_open_from_record,
    epoch_opens_from_records,
    find_epoch_opens,
    latest_epoch_open,
    pin_set_for_terms,
    same_family_epoch_pairs,
)
from capsule_ledger.compiler.terms_desk import (
    ApplicabilitySpec,
    TermDeclaration,
    compile_term,
)

OPERATOR = "test-operator"
DEVELOPER = "test-developer@v1"
T_DIGEST = "a" * 64


def _judged_term_with_spec(term_id: str = "term.judged_care"):
    from capsule_ledger.compiler.terms_desk import JudgeOrRuleSpec

    declaration = Declaration(
        outcome_id=term_id,
        statement="escalations are acknowledged within one business day",
        requires_model_judgment=True,
    )
    return TermDeclaration(
        term_id=term_id,
        statement=declaration.statement,
        clause_ref="contract/§7.1",
        applicability=ApplicabilitySpec(unit="turn"),
        verdict_schema=("pass", "fail"),
        declaration=declaration,
        judge_spec=JudgeOrRuleSpec(
            kind="judge", verdict_schema=("pass", "fail"), model_id="judge-model-x@1", prompt_digest="p" * 64
        ),
    )


def _direct_deterministic_term(term_id: str = "term.direct_deterministic") -> TermDeclaration:
    declaration = Declaration(
        outcome_id=term_id,
        statement="a direct declaration, forward-compiled",
        allowed_actions=("remediation",),
        binding={"action_class": "remediation"},
    )
    return TermDeclaration(
        term_id=term_id,
        statement=declaration.statement,
        clause_ref=None,
        applicability=ApplicabilitySpec(unit="turn"),
        verdict_schema=("pass", "fail"),
        declaration=declaration,
    )


# --- EpochPin / EpochOpen invariants ---------------------------------------


def test_epoch_pin_requires_exactly_one_of_judge_or_rule():
    with pytest.raises(CompilerError, match="neither"):
        EpochPin(term_id="x")
    with pytest.raises(CompilerError, match="both"):
        EpochPin(term_id="x", model_id="m", prompt_digest="p" * 64, rule_digest="r" * 64)


def test_epoch_open_requires_hex64_t_digest():
    with pytest.raises(CompilerError, match="t_digest"):
        EpochOpen(epoch_id="epoch-a", opened_at="2026-08-26T00:00:00Z", t_digest="not-hex", judge_family="openai")


def test_epoch_open_requires_judge_family():
    with pytest.raises(CompilerError, match="judge_family"):
        EpochOpen(epoch_id="epoch-a", opened_at="2026-08-26T00:00:00Z", t_digest=T_DIGEST, judge_family="")


# --- pin_set_for_terms: derived, not hand-typed -----------------------------


def test_pin_set_for_terms_derives_judge_pin_from_compiled_term():
    ct = compile_term(_judged_term_with_spec())
    pins = pin_set_for_terms((ct,))
    assert len(pins) == 1
    assert pins[0].term_id == "term.judged_care"
    assert pins[0].model_id == "judge-model-x@1"
    assert pins[0].prompt_digest == "p" * 64
    assert pins[0].rule_digest is None


def test_pin_set_for_terms_derives_rule_pin_from_compiled_deterministic_term():
    ct = compile_term(_direct_deterministic_term())
    pins = pin_set_for_terms((ct,))
    assert len(pins) == 1
    assert pins[0].rule_digest == ct.f_digest
    assert pins[0].model_id is None


def test_pin_set_for_terms_skips_refused_terms():
    declaration = Declaration(
        outcome_id="term.refused",
        statement="the interaction increased trust",
        effect_claim="agent.caused_resolution",
    )
    term = TermDeclaration(
        term_id="term.refused",
        statement=declaration.statement,
        clause_ref=None,
        applicability=ApplicabilitySpec(unit="turn"),
        verdict_schema=("pass", "fail"),
        declaration=declaration,
    )
    ct = compile_term(term)
    assert ct.refusal_reason_code is not None
    assert pin_set_for_terms((ct,)) == ()


# --- build_epoch_open_capsule: chains via the registered epoch_opens relation


def test_first_epoch_open_chains_to_genesis(signer):
    epoch = EpochOpen(epoch_id="epoch-a", opened_at="2026-08-26T00:00:00Z", t_digest=T_DIGEST, judge_family="openai")
    capsule = build_epoch_open_capsule(epoch, operator=OPERATOR, developer=DEVELOPER, signer=signer)
    assert capsule["chain"] == {"parent_capsule_id": GENESIS_PARENT, "relation": "epoch_opens"}
    assert capsule["asg_payload"]["event"] == EVENT_EPOCH_OPEN
    assert capsule["action_type"] == "fyi"
    assert compute_capsule_id(capsule) == capsule["capsule_id"]


def test_second_epoch_open_chains_to_the_first(store, signer):
    first = EpochOpen(epoch_id="epoch-a", opened_at="2026-08-26T00:00:00Z", t_digest=T_DIGEST, judge_family="openai")
    first_capsule = build_epoch_open_capsule(first, operator=OPERATOR, developer=DEVELOPER, signer=signer)
    store.append(first_capsule, consequential=False)

    previous = latest_epoch_open(store)
    assert previous is not None
    assert previous.epoch_id == "epoch-a"

    second = EpochOpen(
        epoch_id="epoch-b",
        opened_at="2026-08-27T00:00:00Z",
        t_digest=T_DIGEST,
        judge_family="anthropic",
        pins=(EpochPin(term_id="term.judged_care", model_id="claude-x@1", prompt_digest="q" * 64),),
    )
    second_capsule = build_epoch_open_capsule(
        second, operator=OPERATOR, developer=DEVELOPER, signer=signer, previous_epoch_open_capsule_id=first_capsule["capsule_id"]
    )
    store.append(second_capsule, consequential=False)

    assert second_capsule["chain"] == {"parent_capsule_id": first_capsule["capsule_id"], "relation": "epoch_opens"}
    latest = latest_epoch_open(store)
    assert latest.epoch_id == "epoch-b"

    all_opens = find_epoch_opens(store)
    assert [e.epoch_id for e in all_opens] == ["epoch-a", "epoch-b"]


def test_epoch_open_round_trips_through_parse(signer):
    epoch = EpochOpen(
        epoch_id="epoch-a",
        opened_at="2026-08-26T00:00:00Z",
        t_digest=T_DIGEST,
        judge_family="openai",
        pins=(EpochPin(term_id="term.judged_care", model_id="m", prompt_digest="p" * 64),),
    )
    capsule = build_epoch_open_capsule(epoch, operator=OPERATOR, developer=DEVELOPER, signer=signer)
    parsed = epoch_open_from_record(capsule)
    assert parsed == epoch


def test_epoch_open_from_record_returns_none_for_a_different_epoch_opens_producer(signer):
    """A policy-manifest activation shares chain.relation == 'epoch_opens'
    but MUST NOT be misread as a judge epoch -- the two lineages are
    disambiguated by asg_payload.event, not by the chain relation."""
    from capsule_ledger.guards.capsule import build_event_capsule

    other = build_event_capsule(
        operator=OPERATOR,
        developer=DEVELOPER,
        signer=signer,
        event="policy_manifest_activated",
        detail={"manifest_digest": T_DIGEST},
        chain_parent=GENESIS_PARENT,
        chain_relation="epoch_opens",
    )
    assert epoch_open_from_record(other) is None


def test_epoch_opens_from_records_reads_a_plain_records_slice(signer):
    epoch = EpochOpen(epoch_id="epoch-a", opened_at="2026-08-26T00:00:00Z", t_digest=T_DIGEST, judge_family="openai")
    capsule = build_epoch_open_capsule(epoch, operator=OPERATOR, developer=DEVELOPER, signer=signer)
    records = [{"developer": DEVELOPER}, capsule, {"developer": DEVELOPER}]
    found = epoch_opens_from_records(records)
    assert found == (epoch,)


# --- same_family_epoch_pairs: registry-only, no verdict rows needed --------


def test_same_family_epoch_pairs_computed_from_registry_alone():
    a = EpochOpen(epoch_id="epoch-a", opened_at="t1", t_digest=T_DIGEST, judge_family="openai")
    b = EpochOpen(epoch_id="epoch-b", opened_at="t2", t_digest=T_DIGEST, judge_family="openai")
    c = EpochOpen(epoch_id="epoch-c", opened_at="t3", t_digest=T_DIGEST, judge_family="anthropic")
    pairs = same_family_epoch_pairs((a, b, c))
    assert pairs == frozenset({frozenset({"epoch-a", "epoch-b"})})


def test_same_family_epoch_pairs_empty_when_every_epoch_differs():
    a = EpochOpen(epoch_id="epoch-a", opened_at="t1", t_digest=T_DIGEST, judge_family="openai")
    b = EpochOpen(epoch_id="epoch-b", opened_at="t2", t_digest=T_DIGEST, judge_family="anthropic")
    assert same_family_epoch_pairs((a, b)) == frozenset()


def test_same_family_epoch_pairs_never_self_pairs():
    a = EpochOpen(epoch_id="epoch-a", opened_at="t1", t_digest=T_DIGEST, judge_family="openai")
    assert same_family_epoch_pairs((a,)) == frozenset()
