# SPDX-License-Identifier: Apache-2.0
"""``ConfirmConnector``: the pluggable seam between a third system's state and
one fulfillment capsule.

A connector reads whether a third system (an IdP, a ticketing system, a
payments processor) has settled one ``(subject, predicate)`` question --
e.g. ``subject="user-42", predicate="mfa_enabled"`` or
``subject="ticket-9001", predicate="resolved"`` -- and, if it has, reports
what it observed. ``ConfirmIngestEngine`` (``engine.py``) turns that
observation into a signed, sealed fulfillment capsule chained to the
commitment it confirms; the connector itself never touches the ledger,
never signs anything, and never decides what "confirmed" means for the
commitment -- it only reports the third system's own state, honestly.

This module ships one reference implementation
(``connectors/mock_idp.py::MockIdPConnector``) for the demo + fixtures. A
real integration (Okta, Entra, a payments processor's webhook/polling API)
implements this same ``ConfirmConnector`` Protocol against its own
transport -- see ``docs/confirm-connector-interface.md`` for the wiring
guide. Nothing downstream (the capsule shape, the engine, the CLI) changes
when a real connector replaces the mock; the seam is deliberately as thin
as ``guards.signing.Signer``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

__all__ = ["ConfirmObservation", "ConfirmConnector"]


@dataclass(frozen=True)
class ConfirmObservation:
    """One connector read of external-system state for a ``(subject,
    predicate)`` pair.

    ``status`` follows the Effect Record's own reserved vocabulary
    (``agent_action_capsule.EFFECT_STATUSES``): ``"confirmed"`` (the state
    change happened) or ``"failed"`` (the third system explicitly reports
    it did not, or will not, happen). There is no ``"pending"`` value here
    -- a connector with nothing to report yet returns ``None`` from
    ``read_confirmation`` instead of constructing an observation for it, so
    "nothing observed" and "observed as not-yet-settled" can never be
    confused.

    ``evidence`` is the connector's raw structured read from the third
    system (e.g. the IdP's own flag record) -- ``build_confirm_capsule``
    commits it as ``effect.response_digest`` only; it is never stored
    verbatim on the capsule (same discipline as
    ``guards.capsule.ConstraintOutcome.evidence`` -> ``evidence_digest``).
    """

    status: str  # "confirmed" | "failed"
    external_ref: str
    observed_at: str
    evidence: dict = field(default_factory=dict)


@runtime_checkable
class ConfirmConnector(Protocol):
    """Reads a third system's state for one ``(subject, predicate)`` pair.

    ``connector_type`` becomes ``asg_payload.connector_type`` on every
    fulfillment capsule this connector's reads produce -- "which system
    confirmed this" is checkable directly off the capsule, never a separate
    possibly-stale lookup.
    """

    connector_type: str

    def read_confirmation(self, *, subject: str, predicate: str) -> ConfirmObservation | None: ...
