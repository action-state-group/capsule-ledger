# SPDX-License-Identifier: Apache-2.0
"""Cedar interop (design §2.7): "we do not invent a policy language ... for
statements that are authorization-shaped, the industry has converged on
Cedar." This module is deliberately thin on both sides -- an INTEROP
TARGET, never substrate (design §2.7's own line to hold): this codebase
never parses, evaluates, or grades a Cedar policy's correctness. It only
ever (a) pins an imported policy's bytes by digest, so a compiled plan can
cite *which* policy it claims to be authorized under, and (b) renders the
authorization-shaped subset of an already-compiled ``PlanDefinition`` as
Cedar syntax, for a deployment that already runs a Cedar PDP to consume
independently. Neither direction runs a Cedar engine; there isn't one here.

**Import**: the policy's digest lands in ``PlanDefinition.binding``
(``compile.Declaration.cedar_policy_digest`` -- wired into ``binding`` at
compile time, same as any other binding key), so a report can say which
policy governed without this codebase ever re-deriving that policy's
meaning.

**Export**: ``export_authorization_subset`` renders exactly the fields a
Cedar ``permit`` statement can express from a ``PlanDefinition`` --
``allowed_actions`` as the action set and ``binding["subject"]`` (the only
binding key ``plan_containment`` independently verifies -- ``guards/
checks/plan_containment.py``) as the principal. Preconditions, windows, and
every other binding key are NOT authorization-shaped (they are
evidence-shaped -- design §2.7: "wickets check evidence, Cedar checks
authority") and are deliberately left out of the export; a caller needing
them keeps using ``plan.canonical_dict()`` directly.
"""
from __future__ import annotations

from agent_action_capsule.canonical import json_digest
from agent_action_capsule.contracts import is_hex64

from ..guards.plan import PlanDefinition

__all__ = ["cedar_policy_digest", "export_authorization_subset"]


def cedar_policy_digest(policy_text: str) -> str:
    """Pin an imported Cedar policy's bytes by digest -- SHA-256 over the
    JCS-canonical wrapper, the same digest discipline every other artifact
    in this codebase uses, so a Cedar policy digest is comparable/citable
    the same way a plan or fold digest is. This never parses ``policy_text``
    as Cedar syntax; a syntactically invalid policy still digests (pinning
    bytes is not validating them -- validation is the Cedar PDP's job, on
    the other side of the interop boundary)."""
    if not isinstance(policy_text, str) or not policy_text.strip():
        raise ValueError("policy_text must be a non-empty string")
    digest = json_digest({"cedar_policy": policy_text})
    assert is_hex64(digest)  # json_digest always returns hex64; documents the invariant this module relies on
    return digest


def export_authorization_subset(plan: PlanDefinition, *, policy_id: str) -> str:
    """Render the authorization-shaped subset of ``plan`` as a single Cedar
    ``permit`` statement (text). Real, minimal Cedar syntax -- not a
    template placeholder -- but intentionally only the two fields this
    codebase can independently stand behind: the action set
    ``plan_containment`` checks membership in, and the bound subject
    ``plan_containment`` independently re-derives from ``Action.target``
    (``guards/checks/plan_containment.py``'s own docstring on what its pure
    binding check can and cannot verify)."""
    if not policy_id or not policy_id.replace("_", "").isalnum():
        raise ValueError(f"policy_id must be a non-empty identifier-shaped string; got {policy_id!r}")

    action_lines = ",\n        ".join(f'Action::"{verb}"' for verb in plan.allowed_actions)
    subject = plan.binding.get("subject")
    principal_clause = f'principal == Subject::"{subject}"' if subject is not None else "principal"

    return (
        f'@id("{policy_id}")\n'
        f"// generated from plan {plan.outcome_id!r} (digest {plan.definition_digest()})\n"
        f"// authorization-shaped subset only -- preconditions/window are evidence-shaped, not exported.\n"
        f"permit(\n"
        f"    {principal_clause},\n"
        f"    action in [\n"
        f"        {action_lines}\n"
        f"    ],\n"
        f"    resource\n"
        f");\n"
    )
