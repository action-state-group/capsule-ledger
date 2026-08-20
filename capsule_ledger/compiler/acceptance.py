# SPDX-License-Identifier: Apache-2.0
"""T1 (declaration acceptance) and T4 (refusal acknowledgment) -- the two
human touchpoints (design §4) that ``capsule report``'s "what was promised"
block reads, alongside T2 (``scope_census.py``, already shipped in P1).

**Why this lands here, in P4, and not in P3's ``setup confirm``.** P1 already
established the pattern: a touchpoint's sealed-capsule *shape* is schema-layer
work (``scope_census.py``'s T2 builder shipped in P1, even though P3's
``confirm`` verb is what will actually call it from a CLI). T1 and T4 are the
same kind of object -- a signed, recorded act, not setup-verb orchestration
logic -- so they belong beside T2, not inside P3's CLI plumbing. Building
them here unblocks ``capsule report`` (this task) without waiting on P3,
which is still in flight (manager parallel-spawn note, [ldg-cs-p4-capsule-report]).
P3's ``confirm`` command should call these builders directly rather than
re-deriving the shape.

**T1 -- declaration acceptance** (design §4): *"These are the outcomes we
are claiming, and these are the rules for proving them."* A signed capsule
freezing the ``(D, mapping)`` pair -- concretely, the declaration digest
``d_digest`` and the compilation record's own digest ``c_digest`` (C already
binds ``D_digest``/``P_digest``/``F_digest`` together, so citing C's digest
is citing the whole mapping, not just D). ``accepted_by`` is a free-form
identity string (who/what role accepted -- one deployment shape is
vendor-declares, customer-accepts; kept free-form here for the same reason
``Outcome.declared_by`` is free-form in ``packs/schema.py``: the closed-enum
semantics for this field are still open, design §7).

**T4 -- refusal acknowledgment** (design §4): *"When the compiler refuses a
statement, a human must see and accept the refusal."* Chained to the
``compiler.refusal`` capsule it acknowledges -- without this chain, an
auditor cannot tell a refusal that was surfaced and accepted from one nobody
ever looked at, and the design is explicit that this is "the touchpoint most
likely to be dropped as friction... the one that makes the honesty visible
instead of merely present."
"""
from __future__ import annotations

from agent_action_capsule.contracts import is_hex64

from ..guards.capsule import build_event_capsule
from ..guards.signing import Signer

__all__ = [
    "EVENT_DECLARATION_ACCEPTANCE",
    "EVENT_REFUSAL_ACKNOWLEDGMENT",
    "build_declaration_acceptance_capsule",
    "build_refusal_acknowledgment_capsule",
]

EVENT_DECLARATION_ACCEPTANCE = "compiler.declaration_acceptance"
EVENT_REFUSAL_ACKNOWLEDGMENT = "compiler.refusal_acknowledgment"


def build_declaration_acceptance_capsule(
    *,
    d_digest: str,
    c_digest: str,
    accepted_by: str,
    operator: str,
    developer: str,
    signer: Signer,
    timestamp: str | None = None,
    action_id: str | None = None,
    chain_parent: str | None = None,
) -> dict:
    """Seal a T1 acceptance: ``accepted_by`` accepts the declaration
    identified by ``d_digest``, under the mapping frozen in the compilation
    record identified by ``c_digest``. ``chain_parent`` cites the prior
    acceptance this one supersedes (a re-acceptance after a declaration
    change), if any -- same lineage discipline as T2's re-census."""
    if not is_hex64(d_digest):
        raise ValueError(f"d_digest must be a 64-hex SHA-256 digest; got {d_digest!r}")
    if not is_hex64(c_digest):
        raise ValueError(f"c_digest must be a 64-hex SHA-256 digest; got {c_digest!r}")
    if not accepted_by:
        raise ValueError("accepted_by is required -- an acceptance capsule with no accepting identity is not a recorded act")

    detail = {"d_digest": d_digest, "c_digest": c_digest, "accepted_by": accepted_by}
    return build_event_capsule(
        operator=operator,
        developer=developer,
        signer=signer,
        event=EVENT_DECLARATION_ACCEPTANCE,
        detail=detail,
        timestamp=timestamp,
        action_id=action_id or f"compiler.declaration_acceptance/{d_digest}",
        chain_parent=chain_parent,
        chain_relation="follows" if chain_parent else None,
    )


def build_refusal_acknowledgment_capsule(
    *,
    refusal_capsule_id: str,
    acknowledged_by: str,
    operator: str,
    developer: str,
    signer: Signer,
    timestamp: str | None = None,
    action_id: str | None = None,
) -> dict:
    """Seal a T4 acknowledgment, chained to the ``compiler.refusal`` capsule
    it accepts. There is no ``dict`` shortcut accepting the raw refusal
    detail -- only a real refusal capsule's own ``capsule_id`` may be cited,
    same "chain to the real record, never re-describe it" discipline
    ``judge/capsules.py``'s adjudication builder already applies to
    judgments."""
    if not refusal_capsule_id:
        raise ValueError("refusal_capsule_id is required")
    if not acknowledged_by:
        raise ValueError("acknowledged_by is required -- an acknowledgment capsule with no acknowledging identity is not a recorded act")

    detail = {"refusal_capsule_id": refusal_capsule_id, "acknowledged_by": acknowledged_by}
    return build_event_capsule(
        operator=operator,
        developer=developer,
        signer=signer,
        event=EVENT_REFUSAL_ACKNOWLEDGMENT,
        detail=detail,
        timestamp=timestamp,
        action_id=action_id or f"compiler.refusal_acknowledgment/{refusal_capsule_id}",
        chain_parent=refusal_capsule_id,
        chain_relation="confirms",
    )
