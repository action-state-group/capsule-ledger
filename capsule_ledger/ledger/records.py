# SPDX-License-Identifier: Apache-2.0
"""Public value types returned by the ledger query API."""
from __future__ import annotations

from dataclasses import dataclass

__all__ = ["LedgerRecord", "ChainGap"]


@dataclass(frozen=True)
class LedgerRecord:
    """One capsule as stored in the ledger, plus ledger-assigned position.

    ``seq`` is the record's position in this ledger's append order (1-indexed) —
    it is ledger-internal bookkeeping, not part of the capsule envelope itself.
    """

    seq: int
    capsule_id: str
    capsule: dict
    segment: str
    consequential: bool


@dataclass(frozen=True)
class ChainGap:
    """A located finding for a ``chain.parent_capsule_id`` that isn't in the ledger.

    Per the Tamper States design: a gap is a *browsable window*, not a dead end.
    ``edge_before``/``edge_after`` are the nearest ledger-position neighbors of the
    break, so a caller can walk forward from the last-known-good record or backward
    from the next-known-good one.
    """

    missing_parent_id: str
    child: LedgerRecord
    relation: str | None
    edge_before: LedgerRecord | None
    edge_after: LedgerRecord
    window: str
    duration_seconds: float | None
    browsable_from_either_edge: bool = True
