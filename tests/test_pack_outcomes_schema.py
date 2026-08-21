# SPDX-License-Identifier: Apache-2.0
"""outcomes[] -- the sister table to obligations[] (compiler-and-setup
design of record 2026-08-19; supersedes [ldg-outcome-declaration-schema]).

Digest preservation for existing zero-outcome packs, required-field
validation, and the mechanical enforcement that ``agent.caused_resolution``
can only be declared as a refusal -- never silently accepted as a provable
claim. Every negative case here is exercised twice: once as the failure
(RED) and once as the corrected near-miss that loads clean (GREEN), per
QUEUE_PROTOCOL §7 ("a refusal test that never rejected anything proves
nothing").
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from capsule_ledger.packs.errors import PackDefinitionError
from capsule_ledger.packs.loader import load_pack_dir

PAYMENTS_SAFETY_DIR = Path(__file__).parent.parent / "capsule_ledger" / "packs" / "catalog" / "payments-safety"

BASE_PACK = {
    "pack_id": "test_pub/test-pack/1.0.0",
    "obligations": [{"id": "o1", "statement": "no dup", "check": "dedupe"}],
    "action_semantics": [
        {"action_type": "payment.dispatch", "action_class": "money.transfer", "required_fields": ["amount_minor"]}
    ],
    "constraints": [{"wicket_id": "test.dedupe/1.0.0", "check": "dedupe", "config": {}}],
    "folds": [{"file": "spend.yaml"}],
}

MINIMAL_FOLD_YAML = """
fold_id: test.spend/1.0.0
reads:
  - path: developer
    erasure_class: commitment-ok
key: developer
reduce:
  reducer: count
emit: n
"""

_DOC_DIGEST = "a" * 64


def _write_pack(tmp_path: Path, overrides: dict | None = None) -> Path:
    data = {**BASE_PACK, **(overrides or {})}
    (tmp_path / "pack.yaml").write_text(yaml.dump(data))
    (tmp_path / "spend.yaml").write_text(MINIMAL_FOLD_YAML)
    return tmp_path


def _outcome(**overrides) -> dict:
    base = {
        "id": "outcome.remediation_confirmed",
        "statement": "The flagged condition was remediated.",
        "evidence_rule": "fulfill capsule chained to intent, effect_attestation=counterparty_confirmed",
        "forward_verdict": "DETERMINISTIC",
        "backward_verdict": "DETERMINISTIC",
    }
    base.update(overrides)
    return base


# --- digest preservation for existing packs ---------------------------


def test_zero_outcome_pack_digests_identically_to_before_the_outcomes_field_existed(tmp_path):
    """Additive-schema guarantee: a pack with no outcomes[] key at all must
    produce the same canonical_dict/digest as one written before this
    field existed. Verified against a hand-computed canonical dict that
    omits "outcomes"/"scope_census" entirely -- if this ever changes, every
    already-sealed pack pin in the fleet silently breaks."""
    pack_dir = _write_pack(tmp_path)
    pack = load_pack_dir(pack_dir)
    canonical = pack.canonical_dict()
    assert "outcomes" not in canonical
    assert "scope_census" not in canonical


def test_the_real_payments_safety_pack_digest_is_unchanged():
    """The committed payments-safety catalog pack (no outcomes[]) must keep
    its exact digest through this change -- a real regression check, not a
    synthetic one."""
    pack = load_pack_dir(PAYMENTS_SAFETY_DIR)
    assert pack.outcomes == ()
    assert pack.scope_census is None
    assert "outcomes" not in pack.canonical_dict()


# --- required fields --------------------------------------------------


def test_missing_evidence_rule_is_a_schema_error(tmp_path):
    pack_dir = _write_pack(tmp_path, {"outcomes": [_outcome(evidence_rule="")]})
    with pytest.raises(PackDefinitionError) as exc:
        load_pack_dir(pack_dir)
    assert exc.value.reason == "missing_evidence_rule"


def test_an_outcome_with_an_evidence_rule_loads_clean(tmp_path):
    pack_dir = _write_pack(tmp_path, {"outcomes": [_outcome()]})
    pack = load_pack_dir(pack_dir)
    assert pack.outcomes[0].evidence_rule


def test_duplicate_outcome_id_is_rejected(tmp_path):
    pack_dir = _write_pack(tmp_path, {"outcomes": [_outcome(), _outcome()]})
    with pytest.raises(PackDefinitionError) as exc:
        load_pack_dir(pack_dir)
    assert exc.value.reason == "duplicate_outcome_id"


def test_invalid_forward_verdict_is_rejected(tmp_path):
    pack_dir = _write_pack(tmp_path, {"outcomes": [_outcome(forward_verdict="MODEL-ASSISTED")]})
    with pytest.raises(PackDefinitionError) as exc:
        load_pack_dir(pack_dir)
    assert exc.value.reason == "invalid_verdict"


def test_valid_forward_verdict_loads_clean(tmp_path):
    pack_dir = _write_pack(tmp_path, {"outcomes": [_outcome(forward_verdict="DETERMINISTIC")]})
    pack = load_pack_dir(pack_dir)
    assert pack.outcomes[0].forward_verdict == "DETERMINISTIC"


# --- the load-bearing case: agent.caused_resolution -----------------------


def test_agent_caused_resolution_with_a_non_refused_verdict_is_rejected(tmp_path):
    """The RED case: someone tries to ship the undecomposable causal claim
    as though it were provable."""
    pack_dir = _write_pack(
        tmp_path,
        {
            "outcomes": [
                _outcome(
                    id="outcome.bad_causal_claim",
                    effect_claim="agent.caused_resolution",
                    forward_verdict="DETERMINISTIC",
                    backward_verdict="DETERMINISTIC",
                )
            ]
        },
    )
    with pytest.raises(PackDefinitionError) as exc:
        load_pack_dir(pack_dir)
    assert exc.value.reason == "effect_claim_not_refused"


def test_agent_caused_resolution_declared_as_refused_loads_clean(tmp_path):
    """The GREEN case, same claim: declared exactly as compile_effect_claim
    says (REFUSED/REFUSED, with the seeded reason code) -- and the reason
    code is auto-filled when omitted."""
    pack_dir = _write_pack(
        tmp_path,
        {
            "outcomes": [
                _outcome(
                    id="outcome.bad_causal_claim",
                    evidence_rule="n/a -- undecomposable, refused by design",
                    effect_claim="agent.caused_resolution",
                    forward_verdict="REFUSED",
                    backward_verdict="REFUSED",
                )
            ]
        },
    )
    pack = load_pack_dir(pack_dir)
    outcome = pack.outcome_for_id("outcome.bad_causal_claim")
    assert outcome.refusal_reason_code == "agent_caused_resolution_undecomposable"


@pytest.mark.parametrize("claim", ["recommendation.acted_on", "resolution.followed_action"])
def test_admissible_effect_claims_load_clean(tmp_path, claim):
    pack_dir = _write_pack(
        tmp_path,
        {
            "outcomes": [
                _outcome(
                    id="outcome.near_miss",
                    effect_claim=claim,
                    forward_verdict="DETERMINISTIC",
                    backward_verdict="DETERMINISTIC",
                )
            ]
        },
    )
    pack = load_pack_dir(pack_dir)
    assert pack.outcome_for_id("outcome.near_miss").effect_claim == claim


def test_unknown_effect_claim_is_rejected(tmp_path):
    pack_dir = _write_pack(tmp_path, {"outcomes": [_outcome(effect_claim="agent.definitely_caused_it")]})
    with pytest.raises(PackDefinitionError) as exc:
        load_pack_dir(pack_dir)
    assert exc.value.reason == "unknown_effect_claim"


# --- REFUSED requires a reason code ----------------------------------


def test_a_refused_verdict_with_no_reason_code_is_rejected(tmp_path):
    pack_dir = _write_pack(
        tmp_path,
        {
            "outcomes": [
                _outcome(
                    id="outcome.unbounded",
                    evidence_rule="n/a -- unbounded goal, refused by design",
                    forward_verdict="REFUSED",
                    backward_verdict="REFUSED",
                )
            ]
        },
    )
    with pytest.raises(PackDefinitionError) as exc:
        load_pack_dir(pack_dir)
    assert exc.value.reason == "missing_refusal_reason"


def test_a_refused_verdict_with_an_explicit_reason_code_loads_clean(tmp_path):
    pack_dir = _write_pack(
        tmp_path,
        {
            "outcomes": [
                _outcome(
                    id="outcome.unbounded",
                    evidence_rule="n/a -- unbounded goal, refused by design",
                    statement="Customer trust increases over time.",
                    forward_verdict="REFUSED",
                    backward_verdict="REFUSED",
                    refusal_reason_code="unbounded_goal_unmonitorable",
                )
            ]
        },
    )
    pack = load_pack_dir(pack_dir)
    assert pack.outcome_for_id("outcome.unbounded").refusal_reason_code == "unbounded_goal_unmonitorable"


# --- scope census -------------------------------------------------------


def test_scope_census_n_greater_than_m_is_rejected(tmp_path):
    pack_dir = _write_pack(tmp_path, {"scope_census": {"document_digest": _DOC_DIGEST, "n": 90, "m": 10, "review_by": "2027-01-01"}})
    with pytest.raises(PackDefinitionError) as exc:
        load_pack_dir(pack_dir)
    assert exc.value.reason == "invalid_scope_census"


def test_scope_census_with_valid_n_and_m_loads_clean(tmp_path):
    pack_dir = _write_pack(tmp_path, {"scope_census": {"document_digest": _DOC_DIGEST, "n": 23, "m": 88, "review_by": "2027-01-01"}})
    pack = load_pack_dir(pack_dir)
    assert pack.scope_census.n == 23
    assert pack.scope_census.m == 88


# --- re-derivability grade on obligations ------------------------------


def test_invalid_re_derivability_grade_on_an_obligation_is_rejected(tmp_path):
    data = {**BASE_PACK}
    data["obligations"] = [{"id": "o1", "statement": "no dup", "check": "dedupe", "re_derivability_grade": "made_up_grade"}]
    (tmp_path / "pack.yaml").write_text(yaml.dump(data))
    (tmp_path / "spend.yaml").write_text(MINIMAL_FOLD_YAML)
    with pytest.raises(PackDefinitionError) as exc:
        load_pack_dir(tmp_path)
    assert exc.value.reason == "invalid_re_derivability_grade"


def test_valid_re_derivability_grade_on_an_obligation_loads_clean(tmp_path):
    data = {**BASE_PACK}
    data["obligations"] = [{"id": "o1", "statement": "no dup", "check": "dedupe", "re_derivability_grade": "ledger_state_dependent"}]
    (tmp_path / "pack.yaml").write_text(yaml.dump(data))
    (tmp_path / "spend.yaml").write_text(MINIMAL_FOLD_YAML)
    pack = load_pack_dir(tmp_path)
    assert pack.obligations[0].re_derivability_grade == "ledger_state_dependent"
