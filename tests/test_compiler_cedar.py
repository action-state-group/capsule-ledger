# SPDX-License-Identifier: Apache-2.0
"""Cedar interop (design §2.7, build plan Phase 2 item 6): import pins a
policy's digest into P's binding; export renders the authorization-shaped
subset. Interop target, never substrate -- this module never parses or
evaluates Cedar."""
from __future__ import annotations

import pytest
from agent_action_capsule.contracts import is_hex64

from capsule_ledger.compiler.cedar import cedar_policy_digest, export_authorization_subset
from capsule_ledger.compiler.compile import Declaration, compile_declaration


def test_cedar_policy_digest_is_a_real_hex64_digest():
    digest = cedar_policy_digest('permit(principal, action, resource);')
    assert is_hex64(digest)


def test_cedar_policy_digest_is_deterministic():
    text = 'permit(principal, action == Action::"remediate", resource);'
    assert cedar_policy_digest(text) == cedar_policy_digest(text)


def test_cedar_policy_digest_changes_with_the_policy_text():
    a = cedar_policy_digest('permit(principal, action, resource);')
    b = cedar_policy_digest('forbid(principal, action, resource);')
    assert a != b


def test_cedar_policy_digest_rejects_empty_text():
    with pytest.raises(ValueError, match="non-empty"):
        cedar_policy_digest("   ")


def test_import_pins_the_policy_digest_onto_the_compiled_plans_binding():
    digest = cedar_policy_digest('permit(principal, action, resource);')
    d = Declaration(
        outcome_id="workforce.remediation/1.0.0",
        statement="s",
        allowed_actions=("remediate",),
        binding={"subject": "acct-1"},
        cedar_policy_digest=digest,
    )
    compiled = compile_declaration(d)
    assert compiled.forward.plan.binding["cedar_policy_digest"] == digest
    # binding participates in the plan's own digest -- an import is visible
    # in P, never a silent side channel.
    plain = compile_declaration(
        Declaration(
            outcome_id="workforce.remediation/1.0.0",
            statement="s",
            allowed_actions=("remediate",),
            binding={"subject": "acct-1"},
        )
    )
    assert compiled.forward.plan.definition_digest() != plain.forward.plan.definition_digest()


def test_export_renders_the_allowed_action_set_and_bound_subject():
    d = Declaration(
        outcome_id="workforce.remediation/1.0.0",
        statement="s",
        allowed_actions=("remediate", "escalate"),
        binding={"subject": "acct-1"},
    )
    compiled = compile_declaration(d)
    text = export_authorization_subset(compiled.forward.plan, policy_id="remediation_policy")
    assert 'Action::"remediate"' in text
    assert 'Action::"escalate"' in text
    assert 'Subject::"acct-1"' in text
    assert "permit(" in text


def test_export_omits_a_principal_clause_when_no_subject_is_bound():
    d = Declaration(outcome_id="workforce.remediation/1.0.0", statement="s", allowed_actions=("remediate",))
    compiled = compile_declaration(d)
    text = export_authorization_subset(compiled.forward.plan, policy_id="remediation_policy")
    assert "Subject::" not in text
    assert "principal," in text  # unconstrained principal


def test_export_never_leaks_precondition_or_window_content():
    # design §2.7: "wickets check evidence, Cedar checks authority" --
    # preconditions/window are evidence-shaped and must never appear in the
    # exported authorization-shaped subset.
    from capsule_ledger.compiler.compile import GatedPrecondition
    from capsule_ledger.compiler.precondition import PreconditionPrimitive

    d = Declaration(
        outcome_id="workforce.remediation/1.0.0",
        statement="s",
        allowed_actions=("remediate",),
        preconditions=(
            GatedPrecondition(
                action="remediate",
                primitive=PreconditionPrimitive(kind="cite_record_of_kind", params={"record_kind": "incident_ticket"}),
            ),
        ),
        window="7d",
    )
    compiled = compile_declaration(d)
    text = export_authorization_subset(compiled.forward.plan, policy_id="remediation_policy")
    # The window/precondition content must not leak into the exported policy.
    # Check against the policy body only, not the provenance comment: that line
    # carries the plan's opaque hex digest, and a short window token like "7d"
    # can appear inside it purely as coincidental hex (e.g. "...01557a7dbe7c..."),
    # which is not a content leak. Excluding the digest line keeps the check
    # about what is actually exported rather than the digest's random hex.
    body = "\n".join(line for line in text.splitlines() if "digest" not in line)
    assert "incident_ticket" not in body
    assert "7d" not in body


def test_export_rejects_a_non_identifier_policy_id():
    d = Declaration(outcome_id="a.b/1.0.0", statement="s", allowed_actions=("act",))
    compiled = compile_declaration(d)
    with pytest.raises(ValueError, match="policy_id"):
        export_authorization_subset(compiled.forward.plan, policy_id="not a valid id!")
