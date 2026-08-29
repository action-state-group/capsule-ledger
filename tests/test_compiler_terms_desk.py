# SPDX-License-Identifier: Apache-2.0
"""The terms-desk compile profile (terms-to-report design §1/§9): a
report-only profile of the existing outcome compiler, additive on top of
``compile_declaration``/``compiled_declaration_for`` -- never a fork.

Three load-bearing properties, each with a named test below:

1. ``P_i`` compiles ONLY for terms whose forward verdict is DETERMINISTIC
   with a real compiled plan (design §1) -- never for MODEL-ASSISTED,
   REFUSED, or a corpus-graded verdict string with no plan behind it.
2. ``clause_ref`` provenance is walkable end to end: term -> sealed C row
   -> clause_ref (design §1 [rev4] / §3 [rev4]).
3. ``verify_terms_compilation_record`` recomputes from the sealed T itself
   (closing hole 1: check against the source, not just internal drift) and
   independently reconfirms P/F coherence wherever a real plan+fold pair
   was compiled (closing hole 2: digest equality proves co-derivation, not
   correspondence -- the same lesson the compiler's own P/F
   non-correspondence bug taught, re-applied here since this profile does
   not import that fix).
"""

from __future__ import annotations

import io

import pytest

from capsule_ledger.compiler.compile import CompilerError, Declaration
from capsule_ledger.compiler.terms_desk import (
    ApplicabilitySpec,
    JudgeOrRuleSpec,
    TermDeclaration,
    TermsDocument,
    build_terms_compilation_record_capsule,
    compile_term,
    compile_terms_document,
    evaluate_term_fold,
    verify_terms_compilation_record,
)
from capsule_ledger.folds.definition import FilterClause
from capsule_ledger.setup.confirm import confirm_accept, confirm_acknowledge_refusal
from capsule_ledger.setup.declarations import DeclarationStore
from capsule_ledger.setup.observe import ObserveRecorder
from capsule_ledger.setup.propose import persist_proposals, propose_from_ledger

OPERATOR = "test-operator"
DEVELOPER = "test-developer@v1"


def _turn_applicability(**extra_filters: object) -> ApplicabilitySpec:
    filters = tuple(FilterClause(field=k, op="eq", value=v) for k, v in extra_filters.items())
    return ApplicabilitySpec(unit="turn", filters=filters)


def _judge_spec(verdict_schema=("pass", "fail")) -> JudgeOrRuleSpec:
    return JudgeOrRuleSpec(
        kind="judge",
        verdict_schema=verdict_schema,
        model_id="judge-model-x@1",
        prompt_digest="p" * 64,
        sampling={"rate": "1"},
    )


def _observe(store, signer, events):
    recorder = ObserveRecorder(
        ledger=store,
        signer=signer,
        operator=OPERATOR,
        developer=DEVELOPER,
        heartbeat_every=0,
        heartbeat_stream=io.StringIO(),
    )
    return recorder.run(events)


def _confirmed_pack_first_store(store, signer, tmp_path):
    """Pack rows -> census grading -> adopt/narrow/refuse, using the
    existing setup pipeline WHOLE (no new production glue)."""
    events = [
        {"kind": "dispatch", "dispatch_id": "d1", "action_class": "remediation", "tool": "remediate"},
        {"kind": "confirmation", "commitment_ref": "d1", "status": "confirmed"},
    ]
    _observe(store, signer, events)
    proposal_set = propose_from_ledger(store)
    decl_store = DeclarationStore(tmp_path)
    persist_proposals(proposal_set, decl_store)

    # adopt the attainment row (T1)
    confirm_accept(
        "outcome.remediation_confirmed",
        store=decl_store,
        ledger=store,
        signer=signer,
        operator=OPERATOR,
        developer=DEVELOPER,
    )
    # refuse a row the census could never satisfy (T4)
    confirm_acknowledge_refusal(
        "outcome.trust_increased",
        store=decl_store,
        ledger=store,
        signer=signer,
        operator=OPERATOR,
        developer=DEVELOPER,
        acknowledged_by="alice",
    )
    return decl_store


# --- P_i compiles only for deterministic-forward terms with a real plan ----


def test_pack_first_attainment_term_emits_p_and_f(store, signer, tmp_path):
    decl_store = _confirmed_pack_first_store(store, signer, tmp_path)
    stored = decl_store.load("outcome.remediation_confirmed")
    term = TermDeclaration(
        term_id="outcome.remediation_confirmed",
        statement=stored.candidate.statement,
        clause_ref="contract/§4.2",
        applicability=_turn_applicability(),
        verdict_schema=("pass", "fail"),
        stored=stored,
    )
    compiled = compile_term(term)
    assert compiled.f_digest is not None
    assert compiled.p_digest is not None
    assert compiled.judge_or_rule.kind == "deterministic_rule"
    assert compiled.judge_or_rule.rule_digest == compiled.f_digest


def test_model_assisted_term_emits_f_and_j_but_never_p(store, signer, tmp_path):
    declaration = Declaration(
        outcome_id="term.escalation_handled_with_care",
        statement="escalations are acknowledged within one business day",
        requires_model_judgment=True,
    )
    term = TermDeclaration(
        term_id="term.escalation_handled_with_care",
        statement=declaration.statement,
        clause_ref="contract/§7.1",
        applicability=_turn_applicability(),
        verdict_schema=("pass", "fail"),
        declaration=declaration,
        judge_spec=_judge_spec(),
    )
    compiled = compile_term(term)
    assert compiled.f_digest is not None
    assert compiled.j_digest is not None
    assert compiled.p_digest is None
    assert compiled.judge_or_rule.kind == "judge"


def test_offer_response_with_instrumentation_never_emits_p(store, signer, tmp_path):
    """Backward compiles to WITH-INSTRUMENTATION, forward to
    UNAVAILABLE-STATE-REQUIRED -- never DETERMINISTIC, so no P_i either
    way; this exercises the non-attainment pack-first path."""
    _observe(store, signer, [])
    proposal_set = propose_from_ledger(store, allow_zero_coverage=True)
    decl_store = DeclarationStore(tmp_path)
    persist_proposals(proposal_set, decl_store)
    confirm_accept(
        "outcome.person_chose",
        store=decl_store,
        ledger=store,
        signer=signer,
        operator=OPERATOR,
        developer=DEVELOPER,
    )
    stored = decl_store.load("outcome.person_chose")
    term = TermDeclaration(
        term_id="outcome.person_chose",
        statement=stored.candidate.statement,
        clause_ref=None,
        applicability=_turn_applicability(),
        verdict_schema=("accepted", "declined", "deferred", "no_response"),
        stored=stored,
    )
    compiled = compile_term(term)
    assert compiled.p_digest is None
    assert compiled.f_digest is not None


def test_refused_term_has_only_a_digest(store, signer, tmp_path):
    decl_store = _confirmed_pack_first_store(store, signer, tmp_path)
    stored = decl_store.load("outcome.trust_increased")
    term = TermDeclaration(
        term_id="outcome.trust_increased",
        statement=stored.candidate.statement,
        clause_ref="contract/§9.9",
        applicability=_turn_applicability(),
        verdict_schema=("pass", "fail"),
        stored=stored,
    )
    compiled = compile_term(term)
    assert compiled.f_digest is None
    assert compiled.j_digest is None
    assert compiled.p_digest is None
    assert compiled.refusal_reason_code == "unbounded_goal_unmonitorable"


def test_a_deterministic_term_may_not_carry_a_judge_spec():
    declaration = Declaration(
        outcome_id="term.direct_deterministic",
        statement="a direct declaration, forward-compiled",
        allowed_actions=("remediation",),
        binding={"action_class": "remediation"},
    )
    term = TermDeclaration(
        term_id="term.direct_deterministic",
        statement=declaration.statement,
        clause_ref=None,
        applicability=_turn_applicability(),
        verdict_schema=("pass", "fail"),
        declaration=declaration,
        judge_spec=_judge_spec(),
    )
    with pytest.raises(CompilerError, match="not\\s+MODEL-ASSISTED"):
        compile_term(term)


# --- clause_ref provenance is walkable end to end --------------------------


def test_clause_ref_is_walkable_from_sealed_c_back_to_the_term(signer):
    declaration = Declaration(
        outcome_id="term.judged_with_clause",
        statement="the agent never asserts policy that isn't in the policy document",
        requires_model_judgment=True,
    )
    term = TermDeclaration(
        term_id="term.judged_with_clause",
        statement=declaration.statement,
        clause_ref="policy-doc/§2.3(b)",
        applicability=_turn_applicability(),
        verdict_schema=("pass", "fail"),
        declaration=declaration,
        judge_spec=_judge_spec(),
    )
    doc = TermsDocument(terms=(term,))
    compiled_terms = compile_terms_document(doc)
    record = build_terms_compilation_record_capsule(
        compiled_terms, t_digest=doc.digest(), operator=OPERATOR, developer=DEVELOPER, signer=signer
    )
    rows = record["asg_payload"]["detail"]["terms"]
    assert len(rows) == 1
    assert rows[0]["term_id"] == "term.judged_with_clause"
    assert rows[0]["clause_ref"] == "policy-doc/§2.3(b)"


def test_refused_terms_render_with_reason_and_clause_ref(signer):
    """Refusal rows render (design §3): a REFUSED term's clause_ref and
    reason code are still sealed, even with no f/j/p digests."""
    declaration = Declaration(
        outcome_id="term.refused_direct",
        statement="the interaction increased trust",
        effect_claim="agent.caused_resolution",
    )
    term = TermDeclaration(
        term_id="term.refused_direct",
        statement=declaration.statement,
        clause_ref="contract/§11",
        applicability=_turn_applicability(),
        verdict_schema=("pass", "fail"),
        declaration=declaration,
    )
    doc = TermsDocument(terms=(term,))
    compiled_terms = compile_terms_document(doc)
    record = build_terms_compilation_record_capsule(
        compiled_terms, t_digest=doc.digest(), operator=OPERATOR, developer=DEVELOPER, signer=signer
    )
    row = record["asg_payload"]["detail"]["terms"][0]
    assert row["clause_ref"] == "contract/§11"
    assert row["refusal_reason_code"] == "agent_caused_resolution_undecomposable"
    assert "f_digest" not in row
    assert "j_digest" not in row
    assert "p_digest" not in row


# --- verify_terms_compilation_record: recompute + P/F coherence -----------


def _two_term_document(store, signer, tmp_path):
    decl_store = _confirmed_pack_first_store(store, signer, tmp_path)
    attainment = TermDeclaration(
        term_id="outcome.remediation_confirmed",
        statement=decl_store.load("outcome.remediation_confirmed").candidate.statement,
        clause_ref="contract/§4.2",
        applicability=_turn_applicability(),
        verdict_schema=("pass", "fail"),
        stored=decl_store.load("outcome.remediation_confirmed"),
    )
    judged = TermDeclaration(
        term_id="term.judged_care",
        statement="escalations are acknowledged within one business day",
        clause_ref="contract/§7.1",
        applicability=_turn_applicability(),
        verdict_schema=("pass", "fail"),
        declaration=Declaration(
            outcome_id="term.judged_care",
            statement="escalations are acknowledged within one business day",
            requires_model_judgment=True,
        ),
        judge_spec=_judge_spec(),
    )
    return TermsDocument(terms=(attainment, judged))


def test_verify_terms_compilation_record_is_clean_on_an_untampered_record(store, signer, tmp_path):
    doc = _two_term_document(store, signer, tmp_path)
    compiled_terms = compile_terms_document(doc)
    record = build_terms_compilation_record_capsule(
        compiled_terms, t_digest=doc.digest(), operator=OPERATOR, developer=DEVELOPER, signer=signer
    )
    result = verify_terms_compilation_record(record["asg_payload"]["detail"], t_document=doc)
    assert result.drifted is False
    assert result.t_drifted is False
    assert all(not entry.drifted for entry in result.per_term.values())


def test_verify_terms_compilation_record_catches_t_digest_tamper(store, signer, tmp_path):
    doc = _two_term_document(store, signer, tmp_path)
    compiled_terms = compile_terms_document(doc)
    record = build_terms_compilation_record_capsule(
        compiled_terms, t_digest=doc.digest(), operator=OPERATOR, developer=DEVELOPER, signer=signer
    )
    tampered = dict(record["asg_payload"]["detail"])
    tampered["t_digest"] = "0" * 64
    result = verify_terms_compilation_record(tampered, t_document=doc)
    assert result.drifted is True
    assert result.t_drifted is True


def test_verify_terms_compilation_record_catches_a_per_term_digest_tamper(store, signer, tmp_path):
    doc = _two_term_document(store, signer, tmp_path)
    compiled_terms = compile_terms_document(doc)
    record = build_terms_compilation_record_capsule(
        compiled_terms, t_digest=doc.digest(), operator=OPERATOR, developer=DEVELOPER, signer=signer
    )
    detail = record["asg_payload"]["detail"]
    tampered_rows = [dict(r) for r in detail["terms"]]
    for row in tampered_rows:
        if row["term_id"] == "term.judged_care":
            row["f_digest"] = "1" * 64
    tampered = dict(detail, terms=tampered_rows)

    result = verify_terms_compilation_record(tampered, t_document=doc)
    assert result.drifted is True
    assert result.per_term["term.judged_care"].f_drifted is True
    assert result.per_term["outcome.remediation_confirmed"].drifted is False


def test_verify_terms_compilation_record_catches_a_dropped_term(store, signer, tmp_path):
    doc = _two_term_document(store, signer, tmp_path)
    compiled_terms = compile_terms_document(doc)
    record = build_terms_compilation_record_capsule(
        compiled_terms, t_digest=doc.digest(), operator=OPERATOR, developer=DEVELOPER, signer=signer
    )
    detail = record["asg_payload"]["detail"]
    tampered = dict(detail, terms=[r for r in detail["terms"] if r["term_id"] != "term.judged_care"])

    result = verify_terms_compilation_record(tampered, t_document=doc)
    assert result.drifted is True
    assert result.per_term["term.judged_care"].missing_in_sealed is True


def test_verify_terms_compilation_record_catches_pf_incoherence_mutant(signer):
    """Mutant-proof, matching the compiler's own falsification line
    (design/build-plan Phase 2): construct a declaration whose plan admits
    a wider action set than its fold actually counts -- a real P/F
    incoherence -- and show ``verify_terms_compilation_record`` flags it
    even though each half's own digest still matches the sealed record
    (co-derivation, not correspondence)."""
    declaration = Declaration(
        outcome_id="term.incoherent_scope",
        statement="a directly-built declaration whose binding under-covers its allowed actions",
        allowed_actions=("escalate", "remediate"),
        binding={"action_class": "escalate"},  # narrower than allowed_actions -- the bug class
    )
    term = TermDeclaration(
        term_id="term.incoherent_scope",
        statement=declaration.statement,
        clause_ref=None,
        applicability=_turn_applicability(),
        verdict_schema=("pass", "fail"),
        declaration=declaration,
    )
    doc = TermsDocument(terms=(term,))
    compiled_terms = compile_terms_document(doc)
    record = build_terms_compilation_record_capsule(
        compiled_terms, t_digest=doc.digest(), operator=OPERATOR, developer=DEVELOPER, signer=signer
    )

    result = verify_terms_compilation_record(record["asg_payload"]["detail"], t_document=doc)
    assert result.drifted is True
    assert result.per_term["term.incoherent_scope"].pf_incoherent is True
    # neither digest itself drifted -- this is exactly the "digests match,
    # meaning still wrong" case the coherence check exists to catch.
    assert result.per_term["term.incoherent_scope"].f_drifted is False
    assert result.per_term["term.incoherent_scope"].p_drifted is False


def test_verify_terms_compilation_record_mutant_proof_a_coherent_pair_is_not_flagged(signer):
    declaration = Declaration(
        outcome_id="term.coherent_scope",
        statement="a directly-built declaration whose binding matches its allowed actions",
        allowed_actions=("escalate",),
        binding={"action_class": "escalate"},
    )
    term = TermDeclaration(
        term_id="term.coherent_scope",
        statement=declaration.statement,
        clause_ref=None,
        applicability=_turn_applicability(),
        verdict_schema=("pass", "fail"),
        declaration=declaration,
    )
    doc = TermsDocument(terms=(term,))
    compiled_terms = compile_terms_document(doc)
    record = build_terms_compilation_record_capsule(
        compiled_terms, t_digest=doc.digest(), operator=OPERATOR, developer=DEVELOPER, signer=signer
    )
    result = verify_terms_compilation_record(record["asg_payload"]["detail"], t_document=doc)
    assert result.drifted is False
    assert result.per_term["term.coherent_scope"].pf_incoherent is False


# --- TermsDocument / TermDeclaration invariants ----------------------------


def test_terms_document_rejects_duplicate_term_ids():
    declaration = Declaration(outcome_id="dup", statement="s", requires_model_judgment=True)
    term = TermDeclaration(
        term_id="dup",
        statement="s",
        clause_ref=None,
        applicability=_turn_applicability(),
        verdict_schema=("pass", "fail"),
        declaration=declaration,
        judge_spec=_judge_spec(),
    )
    with pytest.raises(CompilerError, match="duplicate term_id"):
        TermsDocument(terms=(term, term))


def test_term_declaration_requires_exactly_one_of_stored_or_declaration():
    with pytest.raises(CompilerError, match="exactly one"):
        TermDeclaration(
            term_id="x",
            statement="s",
            clause_ref=None,
            applicability=_turn_applicability(),
            verdict_schema=("pass", "fail"),
        )


def test_term_declaration_rejects_unconfirmed_proposed_candidate(store, signer, tmp_path):
    _observe(
        store,
        signer,
        [
            {"kind": "dispatch", "dispatch_id": "d1", "action_class": "remediation", "tool": "remediate"},
            {"kind": "confirmation", "commitment_ref": "d1", "status": "confirmed"},
        ],
    )
    proposal_set = propose_from_ledger(store)
    decl_store = DeclarationStore(tmp_path)
    persist_proposals(proposal_set, decl_store)
    stored = decl_store.load("outcome.remediation_confirmed")
    assert stored.acceptance_state == "proposed"
    with pytest.raises(CompilerError, match="proposed"):
        TermDeclaration(
            term_id="outcome.remediation_confirmed",
            statement=stored.candidate.statement,
            clause_ref=None,
            applicability=_turn_applicability(),
            verdict_schema=("pass", "fail"),
            stored=stored,
        )


# --- (range, as_of, epoch) as formal parameters of the term fold -----------


def test_evaluate_term_fold_takes_range_as_of_epoch_as_formal_parameters(store, signer, tmp_path):
    decl_store = _confirmed_pack_first_store(store, signer, tmp_path)
    stored = decl_store.load("outcome.remediation_confirmed")
    term = TermDeclaration(
        term_id="outcome.remediation_confirmed",
        statement=stored.candidate.statement,
        clause_ref=None,
        applicability=_turn_applicability(),
        verdict_schema=("pass", "fail"),
        stored=stored,
    )
    compiled = compile_term(term)

    records = [
        {
            "developer": DEVELOPER,
            "disposition": {"verdict_class": "executed"},
            "asg_payload": {"action_class": "remediation"},
        },
        {
            "developer": DEVELOPER,
            "disposition": {"verdict_class": "executed"},
            "asg_payload": {"action_class": "remediation"},
        },
    ]
    traces_no_epoch = evaluate_term_fold(compiled, records, range_start=0, as_of=None, epoch=None)
    assert traces_no_epoch[DEVELOPER].result == 2

    # epoch is a real, load-bearing filter -- scoping to an epoch no record
    # carries drops the match count to zero without raising, exactly like
    # any other fold filter (spec §3 rule 4: skip-with-count, never error).
    traces_scoped = evaluate_term_fold(compiled, records, range_start=0, as_of=None, epoch="epoch-b")
    assert traces_scoped == {}


def test_evaluate_term_fold_refuses_a_refused_term(store, signer, tmp_path):
    decl_store = _confirmed_pack_first_store(store, signer, tmp_path)
    stored = decl_store.load("outcome.trust_increased")
    term = TermDeclaration(
        term_id="outcome.trust_increased",
        statement=stored.candidate.statement,
        clause_ref=None,
        applicability=_turn_applicability(),
        verdict_schema=("pass", "fail"),
        stored=stored,
    )
    compiled = compile_term(term)
    with pytest.raises(CompilerError, match="REFUSED"):
        evaluate_term_fold(compiled, [])


# --- tier ([ldg-bj-tier-field], backward-judge design §8.2) ---------------
#
# Mirrors ``packs.schema.Outcome.tier``: whether a term gates a session's
# job-success (must_have) or is reported without gating (informational, the
# default). Additive and closed-set -- no per-term target/ratio.


def _declaration_term(**overrides) -> TermDeclaration:
    declaration = Declaration(
        outcome_id="term.tier_probe",
        statement="probe statement for tier tests",
        requires_model_judgment=True,
    )
    kwargs = dict(
        term_id="term.tier_probe",
        statement=declaration.statement,
        clause_ref=None,
        applicability=_turn_applicability(),
        verdict_schema=("pass", "fail"),
        declaration=declaration,
        judge_spec=_judge_spec(),
    )
    kwargs.update(overrides)
    return TermDeclaration(**kwargs)


def test_default_tier_is_informational_and_omitted_from_the_digest():
    """A term that doesn't mention tier at all -- the ordinary case for
    every pre-existing term -- parses as 'informational' and the digest
    renders identically to before this field existed (no 'tier' key at
    all), so no already-sealed T pin moves."""
    term = _declaration_term()
    assert term.tier == "informational"
    doc = TermsDocument(terms=(term,))
    assert "tier" not in doc.canonical_dict()["terms"][0]


def test_invalid_tier_value_is_rejected():
    with pytest.raises(CompilerError, match="tier"):
        _declaration_term(tier="critical")


def test_must_have_tier_renders_in_the_digest():
    term = _declaration_term(tier="must_have")
    doc = TermsDocument(terms=(term,))
    assert doc.canonical_dict()["terms"][0]["tier"] == "must_have"
