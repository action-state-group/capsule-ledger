# SPDX-License-Identifier: Apache-2.0
"""``MockIdPConnector``: a deterministic in-memory stand-in for an identity
provider (Okta/Entra-shaped), used for the demo and for test fixtures.

State is seeded explicitly via ``set_state`` -- no wall-clock, no random
material -- so a caller building fixtures/demos gets byte-identical
capsules for a fixed set of seeded state + ``observed_at`` values, the same
determinism discipline ``examples/two_agents.py`` uses for its own
deterministic simulation.

A real Okta/Entra connector implements the same ``ConfirmConnector``
Protocol against the vendor's API/webhook/polling transport instead of an
in-memory dict -- see ``docs/confirm-connector-interface.md``.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..connector import ConfirmObservation

__all__ = ["MockIdPConnector"]


@dataclass
class MockIdPConnector:
    """Reads one flag per ``(subject, predicate)`` pair, e.g.
    ``read_confirmation(subject="user-42", predicate="mfa_enabled")``.
    Nothing is observed until ``set_state`` seeds it -- models "the third
    system hasn't settled this yet", the ordinary starting state for
    anything just tasked."""

    connector_type: str = "mock-idp"
    _state: dict[tuple[str, str], ConfirmObservation] = field(default_factory=dict, repr=False)

    def set_state(
        self,
        *,
        subject: str,
        predicate: str,
        status: str,
        external_ref: str,
        observed_at: str,
        evidence: dict | None = None,
    ) -> None:
        """Seed (or overwrite) this connector's observation for one
        ``(subject, predicate)`` pair. ``status`` MUST be ``"confirmed"`` or
        ``"failed"`` -- mirrors ``build_confirm_capsule``'s own restriction,
        so a bad seed fails here with a clear reason, not deep inside
        capsule construction."""
        if status not in ("confirmed", "failed"):
            raise ValueError(f"mock IdP status must be 'confirmed' or 'failed', got {status!r}")
        self._state[(subject, predicate)] = ConfirmObservation(
            status=status,
            external_ref=external_ref,
            observed_at=observed_at,
            evidence=evidence if evidence is not None else {"subject": subject, "predicate": predicate, "status": status},
        )

    def clear_state(self, *, subject: str, predicate: str) -> None:
        """Revert to "nothing observed yet" for one pair -- models a demo
        step taken before the third system has settled anything."""
        self._state.pop((subject, predicate), None)

    def read_confirmation(self, *, subject: str, predicate: str) -> ConfirmObservation | None:
        return self._state.get((subject, predicate))
