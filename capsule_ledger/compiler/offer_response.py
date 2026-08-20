# SPDX-License-Identifier: Apache-2.0
"""Offer/response recording -- the denominator primitive (design §4b gap 2).

*An offer was made; a response occurred; the response is recorded whether
or not it was the desired one.* One deployment's negative case is a
decline from a person offered a choice; another's is an operator who read
a recommendation and did something else instead. Same primitive underneath
both, which is exactly why it is named ``offer``/``response``/
``response_class`` here and not ``consent`` -- that word imports one
deployment's domain vocabulary into the shared format, precisely what the
admission rule (design §1: "nothing enters the format on one deployment's
evidence alone") forbids.

Two passive ``fyi`` records, same mechanism ``conversation/capsules.py``
uses: an offer capsule (what was proposed, and to whom) and a response
capsule chained to it (what happened). The response is REQUIRED to exist
for every offer, even when ``response_class="no_response"`` -- an offer
with no matching response capsule is a missing record, not a "no response"
one; recording "nothing happened by <as-of time>" is itself an act, because
without it the positive case (``accepted``) has no denominator.
"""
from __future__ import annotations

from agent_action_capsule.contracts import is_hex64

from ..guards.capsule import build_event_capsule
from ..guards.signing import Signer
from .vocabulary import RESPONSE_CLASSES

__all__ = [
    "EVENT_OFFER",
    "EVENT_RESPONSE",
    "InvalidResponseClass",
    "build_offer_capsule",
    "build_response_capsule",
]

EVENT_OFFER = "compiler.offer"
EVENT_RESPONSE = "compiler.response"


class InvalidResponseClass(ValueError):
    """``response_class`` is not one of ``vocabulary.RESPONSE_CLASSES``."""


def _require_response_class(response_class: str) -> None:
    if response_class not in RESPONSE_CLASSES:
        raise InvalidResponseClass(f"response_class must be one of {sorted(RESPONSE_CLASSES)}; got {response_class!r}")


def _require_offer_digest(offer_digest: str) -> None:
    if not is_hex64(offer_digest):
        raise ValueError(f"offer_digest must be a 64-hex SHA-256 digest; got {offer_digest!r}")


def build_offer_capsule(
    *,
    offer_id: str,
    offer_digest: str,
    operator: str,
    developer: str,
    signer: Signer,
    timestamp: str | None = None,
    action_id: str | None = None,
) -> dict:
    """Seal the offer itself: ``offer_digest`` commits to the offer's own
    content (the recommendation text, the proposed change) without carrying
    that content on-capsule -- same disclose-by-digest discipline as every
    other payload this codebase digests rather than embeds."""
    _require_offer_digest(offer_digest)
    detail = {"offer_id": offer_id, "offer_digest": offer_digest}
    return build_event_capsule(
        operator=operator,
        developer=developer,
        signer=signer,
        event=EVENT_OFFER,
        detail=detail,
        timestamp=timestamp,
        action_id=action_id or f"compiler.offer/{offer_id}",
    )


def build_response_capsule(
    *,
    offer_id: str,
    offer_capsule_id: str,
    response_class: str,
    operator: str,
    developer: str,
    signer: Signer,
    response_digest: str | None = None,
    timestamp: str | None = None,
    action_id: str | None = None,
) -> dict:
    """Seal the response to ``offer_capsule_id``. ``response_digest`` is
    optional and only meaningful for ``accepted``/``declined``/``deferred``
    (a digest of what was said or done); ``no_response`` never carries one
    -- there is nothing to digest, only an as-of claim that none arrived."""
    _require_response_class(response_class)
    if response_class == "no_response" and response_digest is not None:
        raise ValueError("no_response must not carry a response_digest -- there is nothing recorded to digest")
    if response_digest is not None and not is_hex64(response_digest):
        raise ValueError(f"response_digest must be a 64-hex SHA-256 digest; got {response_digest!r}")

    detail: dict = {"offer_id": offer_id, "response_class": response_class}
    if response_digest is not None:
        detail["response_digest"] = response_digest
    return build_event_capsule(
        operator=operator,
        developer=developer,
        signer=signer,
        event=EVENT_RESPONSE,
        detail=detail,
        timestamp=timestamp,
        action_id=action_id or f"compiler.response/{offer_id}",
        chain_parent=offer_capsule_id,
        chain_relation="follows",
    )
