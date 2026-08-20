# SPDX-License-Identifier: Apache-2.0
"""External-system confirmation: a state change in a third system (an IdP
MFA flag, etc.) becomes a fulfillment capsule
chained to the commitment it confirms.

Reference implementation ships against a mock IdP
(``connectors.MockIdPConnector``, for the demo + fixtures); the
``ConfirmConnector`` Protocol (``connector.py``) is the documented seam a
real integration (Okta, Entra, a payments processor) implements instead --
see ``docs/confirm-connector-interface.md``.
"""
from .capsule import (
    COMMITMENT_TYPE_CONFIRMATION,
    COMMITMENT_TYPE_ORIGIN,
    CONFIRMS,
    EFFECT_ATTESTATION_CONNECTOR_READ,
    build_confirm_capsule,
    commitment_type_label,
)
from .connector import ConfirmConnector, ConfirmObservation
from .engine import ConfirmDecision, ConfirmIngestEngine, ConfirmStatus
from .errors import (
    CONFIRM_COMMITMENT_NOT_FOUND,
    CONFIRM_INVALID_STATUS,
    CONFIRM_SIGNER_UNAVAILABLE,
    ConfirmError,
)

__all__ = [
    "CONFIRMS",
    "EFFECT_ATTESTATION_CONNECTOR_READ",
    "COMMITMENT_TYPE_ORIGIN",
    "COMMITMENT_TYPE_CONFIRMATION",
    "commitment_type_label",
    "build_confirm_capsule",
    "ConfirmConnector",
    "ConfirmObservation",
    "ConfirmDecision",
    "ConfirmIngestEngine",
    "ConfirmStatus",
    "ConfirmError",
    "CONFIRM_INVALID_STATUS",
    "CONFIRM_SIGNER_UNAVAILABLE",
    "CONFIRM_COMMITMENT_NOT_FOUND",
]
