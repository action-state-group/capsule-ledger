# SPDX-License-Identifier: Apache-2.0
"""Blast-radius lens: for a target record, how many downstream records cite
it -- directly or transitively -- through ``chain.parent_capsule_id`` links.

The forward-direction counterpart to `capsule blame`'s backward chain walk
(``cli/blame_cmd.py``): blame follows a record's ``chain.parent_capsule_id``
back to what led to it; this follows the same chain edges forward, from a
target to everything that cites it. Same chain vocabulary, reused rather
than reinvented. A structural graph traversal over already-recorded chain
links -- never an inference about what a downstream citation *means*.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..ledger.records import LedgerRecord

__all__ = ["BlastRadius", "compute_blast_radius"]


@dataclass(frozen=True)
class BlastRadius:
    """*target* plus every downstream record reachable via chain links, in
    breadth-first order (direct citers first)."""

    target: LedgerRecord
    downstream: tuple[LedgerRecord, ...]

    @property
    def count(self) -> int:
        return len(self.downstream)


def compute_blast_radius(records: list[LedgerRecord], target: LedgerRecord) -> BlastRadius:
    """Walk forward from *target* through ``chain.parent_capsule_id`` edges
    (child -> parent, followed in reverse: parent -> child) to find every
    record that cites *target*, directly or transitively.

    *records* should be the full ledger scan the caller wants to search --
    downstream records outside that set are invisible to this walk.
    """
    children_of: dict[str, list[LedgerRecord]] = {}
    for r in records:
        chain = r.capsule.get("chain") or {}
        parent_id = chain.get("parent_capsule_id")
        if parent_id:
            children_of.setdefault(parent_id, []).append(r)

    downstream: list[LedgerRecord] = []
    visited = {target.capsule_id}
    queue: list[LedgerRecord] = list(children_of.get(target.capsule_id, []))
    while queue:
        r = queue.pop(0)
        if r.capsule_id in visited:
            continue  # defensive: guards a malformed cyclic chain, should not occur
        visited.add(r.capsule_id)
        downstream.append(r)
        queue.extend(children_of.get(r.capsule_id, []))

    return BlastRadius(target=target, downstream=tuple(downstream))
