# SPDX-License-Identifier: Apache-2.0
"""Named-reason errors for the confirm-ingester (mirrors ``holds/errors.py`` --
every rejection carries a stable ``reason`` code so a test can pin the reason
string, not just "it errored about something")."""
from __future__ import annotations

# Record-build-time (build_confirm_capsule's own invariant).
CONFIRM_INVALID_STATUS = "confirm_invalid_status"

# Ingest-time (ConfirmIngestEngine.ingest's fail-closed reasons).
CONFIRM_SIGNER_UNAVAILABLE = "confirm_signer_unavailable"
CONFIRM_COMMITMENT_NOT_FOUND = "confirm_commitment_not_found"


class ConfirmError(ValueError):
    """A confirmation record fails to build, or ingestion is asked to do
    something it structurally cannot. Carries a stable reason code."""

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(f"{reason}: {message}")
