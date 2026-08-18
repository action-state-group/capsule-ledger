# SPDX-License-Identifier: Apache-2.0
"""``ConfirmIngestEngine``: reads one connector's state for a ``(subject,
predicate)`` pair and, if the third system has settled it one way or the
other, seals a fulfillment capsule chained to the commitment it confirms.

Idempotent by ``effect.external_ref``: re-ingesting the same connector event
against the same commitment never appends a second capsule -- a
poll-until-confirmed caller (or a retried CLI invocation) can call
``ingest`` on a fixed interval without spamming the ledger with duplicate
fulfillment records for the same third-system event.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from ..guards.signing import Signer, SigningKeyUnavailable
from ..ledger.api import LedgerAPI
from .capsule import CONFIRMS, build_confirm_capsule
from .connector import ConfirmConnector
from .errors import CONFIRM_COMMITMENT_NOT_FOUND, CONFIRM_SIGNER_UNAVAILABLE

__all__ = ["ConfirmStatus", "ConfirmDecision", "ConfirmIngestEngine"]


class ConfirmStatus(str, Enum):
    PENDING = "pending"  # connector observed nothing yet; no capsule appended
    RECORDED = "recorded"  # a fresh fulfillment capsule was appended
    ALREADY_RECORDED = "already_recorded"  # idempotent re-ingest of a known external_ref
    ERROR = "error"  # could not record (signer unavailable, commitment not found)


@dataclass(frozen=True)
class ConfirmDecision:
    status: ConfirmStatus
    capsule: dict | None
    reason: str
    reason_code: str | None = None
    # The connector's own "confirmed" | "failed" verdict, set whenever a
    # fulfillment capsule exists for this call (RECORDED or ALREADY_RECORDED).
    effect_status: str | None = None


class ConfirmIngestEngine:
    def __init__(
        self,
        *,
        ledger: LedgerAPI,
        connector: ConfirmConnector,
        signer_provider: Callable[[], Signer | None],
        manifest_digest: str | None = None,
    ) -> None:
        self._ledger = ledger
        self._connector = connector
        self._signer_provider = signer_provider
        self._manifest_digest = manifest_digest

    def _get_signer(self) -> Signer | None:
        try:
            return self._signer_provider()
        except SigningKeyUnavailable:
            return None

    def _existing(self, commitment_capsule_id: str, external_ref: str) -> dict | None:
        """The earliest already-sealed fulfillment capsule chained to this
        commitment for this connector event, if any -- mirrors
        ``holds/engine.py``'s ``hold_status`` full-scan-for-chained-record
        pattern (this codebase's established shape for "look up a record by
        what it's chained to", not a new lookup mechanism)."""
        for record in self._ledger.scan():
            chain = record.capsule.get("chain") or {}
            if chain.get("parent_capsule_id") != commitment_capsule_id or chain.get("relation") != CONFIRMS:
                continue
            effect = record.capsule.get("effect") or {}
            if effect.get("external_ref") == external_ref:
                return record.capsule
        return None

    def ingest(self, commitment_capsule_id: str, *, subject: str, predicate: str) -> ConfirmDecision:
        commitment = self._ledger.fetch(commitment_capsule_id)
        if commitment is None:
            return ConfirmDecision(
                status=ConfirmStatus.ERROR,
                capsule=None,
                reason=f"commitment {commitment_capsule_id[:16]}… not found; nothing to chain a confirmation to",
                reason_code=CONFIRM_COMMITMENT_NOT_FOUND,
            )

        observation = self._connector.read_confirmation(subject=subject, predicate=predicate)
        if observation is None:
            return ConfirmDecision(
                status=ConfirmStatus.PENDING,
                capsule=None,
                reason=f"{self._connector.connector_type}: no observation yet for {subject}/{predicate}",
            )

        existing = self._existing(commitment_capsule_id, observation.external_ref)
        if existing is not None:
            return ConfirmDecision(
                status=ConfirmStatus.ALREADY_RECORDED,
                capsule=existing,
                reason=f"already recorded (external_ref={observation.external_ref})",
                effect_status=(existing.get("effect") or {}).get("status"),
            )

        signer = self._get_signer()
        if signer is None:
            return ConfirmDecision(
                status=ConfirmStatus.ERROR,
                capsule=None,
                reason="signing key unavailable; fail closed, an unsigned record is not a record",
                reason_code=CONFIRM_SIGNER_UNAVAILABLE,
            )

        capsule = build_confirm_capsule(
            commitment_capsule_id=commitment_capsule_id,
            operator=commitment.capsule.get("operator", ""),
            developer=commitment.capsule.get("developer", ""),
            connector_type=self._connector.connector_type,
            subject=subject,
            predicate=predicate,
            status=observation.status,
            external_ref=observation.external_ref,
            evidence=observation.evidence,
            signer=signer,
            observed_at=observation.observed_at,
            manifest_digest=self._manifest_digest,
        )
        self._ledger.append(capsule, consequential=True)
        return ConfirmDecision(
            status=ConfirmStatus.RECORDED,
            capsule=capsule,
            reason=f"recorded {observation.status} confirmation (external_ref={observation.external_ref})",
            effect_status=observation.status,
        )
