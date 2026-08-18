# SPDX-License-Identifier: Apache-2.0
"""Novelty lens: flag a record whose action verb has never occurred before
for that record's own agent, in ledger append order.

Structural only: a per-agent set-membership check over already-recorded
action verbs (the ``action_id`` verb, e.g. "approve_purchase") -- counting
and comparing IDs already on the ledger, never an inference about what a
new verb *means* or whether it's actually dangerous. An agent's first
``min_history`` records are never judged: with no prior history there is
nothing for a record to be "unlike".
"""
from __future__ import annotations

from dataclasses import dataclass

from ..ledger.records import LedgerRecord
from ._common import record_verb

__all__ = ["NoveltyFinding", "find_novel_records"]


@dataclass(frozen=True)
class NoveltyFinding:
    """One record whose verb has no precedent in its own agent's prior history."""

    record: LedgerRecord
    verb: str
    prior_verbs: frozenset[str]


def find_novel_records(records: list[LedgerRecord], *, min_history: int = 1) -> list[NoveltyFinding]:
    """Scan *records* (assumed already in ledger append order) and return one
    :class:`NoveltyFinding` per record whose verb has never appeared before
    for that record's own ``developer``.
    """
    seen_verbs: dict[str, set[str]] = {}
    history_count: dict[str, int] = {}
    findings: list[NoveltyFinding] = []

    for record in records:
        developer = record.capsule.get("developer") or ""
        verb = record_verb(record.capsule)
        prior = seen_verbs.setdefault(developer, set())
        count = history_count.get(developer, 0)

        if count >= min_history and verb not in prior:
            findings.append(NoveltyFinding(record=record, verb=verb, prior_verbs=frozenset(prior)))

        prior.add(verb)
        history_count[developer] = count + 1

    return findings
