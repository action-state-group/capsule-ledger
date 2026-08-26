# SPDX-License-Identifier: Apache-2.0
"""Offer/response recording (design §4b gap 2): the denominator primitive,
named response_class -- never consent. A response is required to exist for
every offer, even when nothing happened by some as-of time."""
from __future__ import annotations

import hashlib

import pytest

from capsule_ledger.compiler.offer_response import (
    EVENT_OFFER,
    EVENT_RESPONSE,
    InvalidResponseClass,
    build_offer_capsule,
    build_response_capsule,
)
from capsule_ledger.compiler.vocabulary import RESPONSE_CLASSES

OPERATOR = "test-operator"
DEVELOPER = "test-developer@v1"


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_offer_capsule_round_trips(signer):
    offer = build_offer_capsule(
        offer_id="offer-1", offer_digest=_digest("offer text"), operator=OPERATOR, developer=DEVELOPER, signer=signer
    )
    assert offer["asg_payload"]["event"] == EVENT_OFFER
    assert offer["asg_payload"]["detail"]["offer_id"] == "offer-1"
    assert offer["action_type"] == "fyi"


def test_offer_capsule_rejects_a_non_digest_offer_digest(signer):
    with pytest.raises(ValueError, match="offer_digest"):
        build_offer_capsule(offer_id="offer-1", offer_digest="not-a-digest", operator=OPERATOR, developer=DEVELOPER, signer=signer)


@pytest.mark.parametrize("response_class", sorted(RESPONSE_CLASSES))
def test_response_capsule_accepts_every_registered_class(signer, response_class):
    offer = build_offer_capsule(
        offer_id="offer-1", offer_digest=_digest("offer"), operator=OPERATOR, developer=DEVELOPER, signer=signer
    )
    response_digest = None if response_class == "no_response" else _digest(response_class)
    response = build_response_capsule(
        offer_id="offer-1",
        offer_capsule_id=offer["capsule_id"],
        response_class=response_class,
        operator=OPERATOR,
        developer=DEVELOPER,
        signer=signer,
        response_digest=response_digest,
    )
    assert response["asg_payload"]["event"] == EVENT_RESPONSE
    assert response["asg_payload"]["detail"]["response_class"] == response_class
    assert response["chain"]["parent_capsule_id"] == offer["capsule_id"]


def test_response_capsule_rejects_an_unregistered_response_class(signer):
    offer = build_offer_capsule(
        offer_id="offer-1", offer_digest=_digest("offer"), operator=OPERATOR, developer=DEVELOPER, signer=signer
    )
    with pytest.raises(InvalidResponseClass):
        build_response_capsule(
            offer_id="offer-1",
            offer_capsule_id=offer["capsule_id"],
            response_class="consent",  # the exact word the design rules out
            operator=OPERATOR,
            developer=DEVELOPER,
            signer=signer,
        )


def test_no_response_must_not_carry_a_response_digest(signer):
    offer = build_offer_capsule(
        offer_id="offer-1", offer_digest=_digest("offer"), operator=OPERATOR, developer=DEVELOPER, signer=signer
    )
    with pytest.raises(ValueError, match="no_response"):
        build_response_capsule(
            offer_id="offer-1",
            offer_capsule_id=offer["capsule_id"],
            response_class="no_response",
            operator=OPERATOR,
            developer=DEVELOPER,
            signer=signer,
            response_digest=_digest("something"),
        )
