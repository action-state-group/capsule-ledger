# SPDX-License-Identifier: Apache-2.0
"""The dual compiler (design §0/§2.1/§2.2, build plan Phase 2 item 1-3):
D -> P + F + C sealed. This is the P2 acceptance surface, verbatim:

  "'Act in good faith' compiles to (UNAVAILABLE-MODEL-REQUIRED,
  MODEL-ASSISTED). `agent.caused_resolution` refuses with a reason code.
  Every precondition primitive's vector pair passes in both directions.
  Falsification: mutate the compiler so P and F derive from different
  declarations and show the C check goes RED. If that mutant passes, C is
  decoration."
"""
from __future__ import annotations

import hashlib

import pytest

from capsule_ledger.compiler.compile import (
    CompiledDeclaration,
    CompilerError,
    Declaration,
    GatedPrecondition,
    compile_declaration,
    seal_compilation_record,
    verify_compilation_record,
    wicket_entry_for,
)
from capsule_ledger.compiler.precondition import PreconditionPrimitive
from capsule_ledger.guards.plan import PlanDefinition
from capsule_ledger.guards.wickets.definition import WicketDefinition

OPERATOR = "test-operator"
DEVELOPER = "test-developer@v1"


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _cite_primitive(record_kind: str = "incident_ticket") -> PreconditionPrimitive:
    return PreconditionPrimitive(kind="cite_record_of_kind", params={"record_kind": record_kind})


# --- the two named acceptance lines ------------------------------------------


def test_act_in_good_faith_compiles_to_the_canonical_pair():
    d = Declaration(
        outcome_id="workforce.acted_in_good_faith/1.0.0",
        statement="Act in good faith.",
        requires_model_judgment=True,
    )
    compiled = compile_declaration(d)
    assert compiled.verdict_pair.forward == "UNAVAILABLE-MODEL-REQUIRED"
    assert compiled.verdict_pair.backward == "MODEL-ASSISTED"
    # the judge is never in the enforcement path: no plan is ever emitted
    # for a model-judgment statement.
    assert compiled.forward.plan is None
    # but a real, digestible backward artifact still exists -- unavailable
    # forward is not the same as refused.
    assert compiled.backward.fold is not None


def test_agent_caused_resolution_refuses_with_a_reason_code():
    d = Declaration(
        outcome_id="workforce.agent_caused_satisfaction/1.0.0",
        statement="The agent's recommendation is what caused the customer to remain satisfied.",
        effect_claim="agent.caused_resolution",
    )
    compiled = compile_declaration(d)
    assert compiled.verdict_pair.forward == "REFUSED"
    assert compiled.verdict_pair.backward == "REFUSED"
    assert compiled.forward.refusal_reason_code == "agent_caused_resolution_undecomposable"
    assert compiled.backward.refusal_reason_code == "agent_caused_resolution_undecomposable"
    assert compiled.forward.plan is None
    assert compiled.backward.fold is None


def test_admissible_effect_claim_compiles_deterministically_both_ways():
    d = Declaration(
        outcome_id="retail.exchange_recommended_and_acted_on/1.0.0",
        statement="The agent recommended an exchange and the customer's own action carried it out.",
        effect_claim="recommendation.acted_on",
        allowed_actions=("recommend_exchange",),
    )
    compiled = compile_declaration(d)
    assert compiled.verdict_pair.forward == "DETERMINISTIC"
    assert compiled.verdict_pair.backward == "DETERMINISTIC"
    assert compiled.forward.plan is not None


# --- forward compile: D -> P -------------------------------------------------


def test_precondition_driven_declaration_compiles_a_real_plan_definition():
    d = Declaration(
        outcome_id="workforce.remediation_completed/1.0.0",
        statement="A flagged incident is remediated.",
        allowed_actions=("remediate",),
        preconditions=(GatedPrecondition(action="remediate", primitive=_cite_primitive()),),
        binding={"subject": "acct-42"},
    )
    compiled = compile_declaration(d)
    plan = compiled.forward.plan
    assert isinstance(plan, PlanDefinition)
    assert plan.outcome_id == d.outcome_id
    assert plan.allowed_actions == ("remediate",)
    assert plan.binding == {"subject": "acct-42"}
    precondition = plan.precondition_for("remediate")
    assert precondition is not None
    assert precondition.citing == "cite_record_of_kind:record_kind=incident_ticket"


def test_p_digest_is_the_plans_own_definition_digest_not_a_wrapper():
    # design/build-plan: "P's digest is a definition digest we already
    # compute and pin. This is wiring, not architecture." -- confirms
    # ForwardCompilation doesn't obscure the plan's own re-derivable digest.
    d = Declaration(outcome_id="a.b/1.0.0", statement="s", allowed_actions=("act",))
    compiled = compile_declaration(d)
    envelope = compiled.forward.canonical_dict()
    assert envelope["plan"] == compiled.forward.plan.canonical_dict()


def test_precondition_naming_an_action_outside_allowed_actions_is_rejected():
    with pytest.raises(CompilerError, match="allowed_actions"):
        Declaration(
            outcome_id="a.b/1.0.0",
            statement="s",
            allowed_actions=("remediate",),
            preconditions=(GatedPrecondition(action="escalate", primitive=_cite_primitive()),),
        )


def test_declaration_with_no_action_space_and_no_model_flag_cannot_compile():
    d = Declaration(outcome_id="a.b/1.0.0", statement="nothing to check")
    with pytest.raises(CompilerError, match="nothing to compile forward against"):
        compile_declaration(d)


def test_invalid_effect_claim_is_rejected_at_declaration_time():
    with pytest.raises(CompilerError, match="effect_claim"):
        Declaration(outcome_id="a.b/1.0.0", statement="s", effect_claim="not.a.real.claim")


def test_wicket_entry_for_wraps_p_as_the_literal_wicket_shape():
    d = Declaration(outcome_id="a.b/1.0.0", statement="s", allowed_actions=("act",))
    compiled = compile_declaration(d)
    wicket = wicket_entry_for(compiled.forward.plan, wicket_id="a.b_wicket/1.0.0")
    assert isinstance(wicket, WicketDefinition)
    assert wicket.check == "plan_containment"
    assert wicket.config == compiled.forward.plan.canonical_dict()
    # the plan's own digest is unaffected by being quoted inside a wicket.
    assert compiled.forward.plan.definition_digest() != wicket.definition_digest()


# --- sealing and the C check (falsification target) -------------------------


def _compile_remediation(allowed_actions=("remediate",)) -> CompiledDeclaration:
    return compile_declaration(
        Declaration(
            outcome_id="workforce.remediation_completed/1.0.0",
            statement="A flagged incident is remediated.",
            allowed_actions=allowed_actions,
            preconditions=(GatedPrecondition(action="remediate", primitive=_cite_primitive()),)
            if "remediate" in allowed_actions
            else (),
        )
    )


def test_seal_and_verify_round_trips_clean_for_the_same_declaration(signer):
    compiled = _compile_remediation()
    d_digest = _digest("D")
    cap = seal_compilation_record(compiled, d_digest=d_digest, operator=OPERATOR, developer=DEVELOPER, signer=signer)
    detail = cap["asg_payload"]["detail"]
    assert detail["p_digest"] == compiled.forward.digest()
    assert detail["f_digest"] == compiled.backward.digest()

    result = verify_compilation_record(detail, recompiled=_compile_remediation(), d_digest=d_digest)
    assert result.drifted is False
    assert result.p_drifted is False
    assert result.f_drifted is False


def test_falsification_mutated_declaration_makes_the_c_check_go_red(signer):
    """THE required falsification test (build plan Phase 2 acceptance
    line): mutate the compiler so P and F derive from a different
    declaration than the one C claims to bind, and confirm the check
    catches it. If this test cannot fail, C is decoration."""
    original = _compile_remediation(allowed_actions=("remediate",))
    d_digest = _digest("D")
    cap = seal_compilation_record(
        original, d_digest=d_digest, operator=OPERATOR, developer=DEVELOPER, signer=signer
    )
    detail = cap["asg_payload"]["detail"]

    mutated = _compile_remediation(allowed_actions=("remediate", "escalate_to_manager"))
    drift = verify_compilation_record(detail, recompiled=mutated, d_digest=d_digest)

    assert drift.drifted is True
    assert drift.p_drifted is True  # the allowed-action set changed -- P's digest must move


def test_falsification_mutant_is_provably_not_a_vacuous_pass(signer):
    # The mutant proof itself, proven: force the SAME (unmutated) recompile
    # through verify_compilation_record and confirm it does NOT flag drift
    # -- otherwise "drifted=True" above could just be a check that always
    # returns True.
    compiled = _compile_remediation()
    d_digest = _digest("D")
    cap = seal_compilation_record(compiled, d_digest=d_digest, operator=OPERATOR, developer=DEVELOPER, signer=signer)
    detail = cap["asg_payload"]["detail"]
    clean = verify_compilation_record(detail, recompiled=_compile_remediation(), d_digest=d_digest)
    assert clean.drifted is False


def test_refused_declarations_seal_a_record_with_no_plan_or_fold_but_still_drift_detectable(signer):
    refused = compile_declaration(
        Declaration(
            outcome_id="workforce.agent_caused_satisfaction/1.0.0",
            statement="s",
            effect_claim="agent.caused_resolution",
        )
    )
    d_digest = _digest("D")
    cap = seal_compilation_record(refused, d_digest=d_digest, operator=OPERATOR, developer=DEVELOPER, signer=signer)
    detail = cap["asg_payload"]["detail"]
    # a non-refused recompile of "the same" outcome id must still be caught
    # as drift -- REFUSED is a real, digestible verdict, not an escape hatch.
    admissible_recompile = compile_declaration(
        Declaration(
            outcome_id="workforce.agent_caused_satisfaction/1.0.0",
            statement="s",
            effect_claim="recommendation.acted_on",
            allowed_actions=("recommend",),
        )
    )
    drift = verify_compilation_record(detail, recompiled=admissible_recompile, d_digest=d_digest)
    assert drift.drifted is True


def test_over_breadth_is_none_when_no_plan_was_compiled():
    compiled = compile_declaration(
        Declaration(outcome_id="a.b/1.0.0", statement="act in good faith", requires_model_judgment=True)
    )
    assert compiled.over_breadth is None


def test_over_breadth_is_the_admitted_action_space_size():
    compiled = _compile_remediation(allowed_actions=("remediate", "escalate"))
    assert compiled.over_breadth == 2
