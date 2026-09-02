# SPDX-License-Identifier: Apache-2.0
"""Append-only capsule store: JSONL segments (source of truth) + a SQLite index.

**Graduated to ``cll.ledger.store`` (2026-09-01, W3.1 CLL extraction;**
action-state-strategy/docs/strategy/w3-ledger-dissolution-lib-per-spec-2026-09-01.md).
Unlike its sibling modules in this package (``admission.py``/``api.py``/
``records.py``, now pure ``sys.modules`` aliases), this module is NOT a pure
alias: :class:`LedgerStore` here is a thin subclass that layers this repo's
own time-fenced key-revocation check (``ledger/revocation.py``) back onto
``verify()`` via the ``extra_findings`` composition seam
``cll.ledger.store.LedgerStore`` exposes for exactly this purpose. ``cll``
itself must not depend on guard/policy-layer product code -- see that
module's docstring for the full reasoning. Every other behavior (JSONL
segments, the SQLite index, the read/scan/fetch path, chain-gap detection)
is exactly ``cll.ledger.store.LedgerStore``'s, inherited unchanged.
"""
from __future__ import annotations

from agent_action_capsule import Finding
from cll.ledger.records import LedgerRecord
from cll.ledger.store import _DEFAULT_SEGMENT_MAX_RECORDS
from cll.ledger.store import LedgerStore as _CllLedgerStore

from .revocation import build_key_timeline, check_time_fenced_revocation

__all__ = ["LedgerStore"]


def _revocation_finding(store: "LedgerStore", record: LedgerRecord) -> Finding | None:
    timeline = build_key_timeline(store)
    revocation = check_time_fenced_revocation(record.capsule, timeline)
    if not revocation.ok:
        return Finding("key_revoked_at_timestamp", revocation.reason, severity="error")
    return None


class LedgerStore(_CllLedgerStore):
    """:class:`cll.ledger.store.LedgerStore` plus this repo's time-fenced
    key-revocation check on :meth:`verify` -- see the module docstring."""

    def __init__(self, root, *, segment_max_records: int = _DEFAULT_SEGMENT_MAX_RECORDS):
        super().__init__(root, segment_max_records=segment_max_records, extra_findings=(_revocation_finding,))
