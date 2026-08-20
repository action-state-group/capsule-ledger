# SPDX-License-Identifier: Apache-2.0
"""T1 (declaration acceptance) and T4 (refusal acknowledgment) -- the two
touchpoints ``capsule report``'s "what was promised" / not-claimable
register read (design §4, §3.6)."""
from __future__ import annotations

import hashlib

import pytest

from capsule_ledger.compiler.acceptance import (
    EVENT_DECLARATION_ACCEPTANCE,
    EVENT_REFUSAL_ACKNOWLEDGMENT,
    build_declaration_acceptance_capsule,
    build_refusal_acknowledgment_capsule,
)

OPERATOR = "test-operator"
DEVELOPER = "test-developer@v1"


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- T1: declaration acceptance --------------------------------------------


def test_declaration_acceptance_seals_the_d_and_c_digest_pair(signer):
    cap = build_declaration_acceptance_capsule(
        d_digest=_digest("D"),
        c_digest=_digest("C"),
        accepted_by="vendor",
        operator=OPERATOR,
        developer=DEVELOPER,
        signer=signer,
    )
    assert cap["asg_payload"]["event"] == EVENT_DECLARATION_ACCEPTANCE
    assert cap["asg_payload"]["detail"] == {
        "d_digest": _digest("D"),
        "c_digest": _digest("C"),
        "accepted_by": "vendor",
    }


def test_declaration_acceptance_rejects_a_non_digest_d_digest(signer):
    with pytest.raises(ValueError, match="d_digest"):
        build_declaration_acceptance_capsule(
            d_digest="not-a-digest", c_digest=_digest("C"), accepted_by="vendor",
            operator=OPERATOR, developer=DEVELOPER, signer=signer,
        )


def test_declaration_acceptance_rejects_a_non_digest_c_digest(signer):
    with pytest.raises(ValueError, match="c_digest"):
        build_declaration_acceptance_capsule(
            d_digest=_digest("D"), c_digest="not-a-digest", accepted_by="vendor",
            operator=OPERATOR, developer=DEVELOPER, signer=signer,
        )


def test_declaration_acceptance_requires_an_accepting_identity(signer):
    with pytest.raises(ValueError, match="accepted_by"):
        build_declaration_acceptance_capsule(
            d_digest=_digest("D"), c_digest=_digest("C"), accepted_by="",
            operator=OPERATOR, developer=DEVELOPER, signer=signer,
        )


def test_declaration_acceptance_chains_to_a_prior_acceptance_on_re_acceptance(signer):
    first = build_declaration_acceptance_capsule(
        d_digest=_digest("D"), c_digest=_digest("C"), accepted_by="vendor",
        operator=OPERATOR, developer=DEVELOPER, signer=signer,
    )
    second = build_declaration_acceptance_capsule(
        d_digest=_digest("D2"), c_digest=_digest("C2"), accepted_by="vendor",
        operator=OPERATOR, developer=DEVELOPER, signer=signer,
        chain_parent=first["capsule_id"],
    )
    assert second["chain"]["parent_capsule_id"] == first["capsule_id"]


# --- T4: refusal acknowledgment ---------------------------------------------


def test_refusal_acknowledgment_chains_to_the_refusal_it_accepts(signer):
    refusal_capsule_id = _digest("refusal-cap")
    cap = build_refusal_acknowledgment_capsule(
        refusal_capsule_id=refusal_capsule_id,
        acknowledged_by="grc-reviewer",
        operator=OPERATOR,
        developer=DEVELOPER,
        signer=signer,
    )
    assert cap["asg_payload"]["event"] == EVENT_REFUSAL_ACKNOWLEDGMENT
    assert cap["asg_payload"]["detail"] == {
        "refusal_capsule_id": refusal_capsule_id,
        "acknowledged_by": "grc-reviewer",
    }
    assert cap["chain"] == {"parent_capsule_id": refusal_capsule_id, "relation": "confirms"}


def test_refusal_acknowledgment_requires_a_refusal_capsule_id(signer):
    with pytest.raises(ValueError, match="refusal_capsule_id"):
        build_refusal_acknowledgment_capsule(
            refusal_capsule_id="", acknowledged_by="grc-reviewer",
            operator=OPERATOR, developer=DEVELOPER, signer=signer,
        )


def test_refusal_acknowledgment_requires_an_acknowledging_identity(signer):
    with pytest.raises(ValueError, match="acknowledged_by"):
        build_refusal_acknowledgment_capsule(
            refusal_capsule_id="refusal-cap-id-123", acknowledged_by="",
            operator=OPERATOR, developer=DEVELOPER, signer=signer,
        )
