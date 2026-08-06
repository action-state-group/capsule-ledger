# SPDX-License-Identifier: Apache-2.0
"""Wires T2's ``LedgerAPI`` to an MMR-backed inclusion/range-proof index.

``MmrLedger`` is a decorator over any ``LedgerAPI`` implementation (T2's
``LedgerStore``, or a future remote binding) -- it only ever calls
``append``/``scan``/``fetch``/``find_gaps``/``verify`` on the wrapped object,
never reaching around the interface into raw storage.

Two wiring styles are supported rather than picking one:

- **Automatic**: every capsule appended *through* this wrapper's own
  ``append()`` is folded into the MMR immediately, in-line.
- **Explicit catch-up**: ``sync()`` scans the wrapped ledger and folds in any
  records this index hasn't seen yet. This covers a ledger populated some
  other way (``LedgerStore.import_jsonl``, a pre-existing store opened
  fresh, or another process's writer) without this module reaching into
  ``LedgerStore`` internals or requiring a change to T2's own ``append()``
  (which is out of this task's scope -- T2's file belongs to another track).

Leaf ordering: MMR ``leaf_index == ledger seq - 1``. ``LedgerRecord.seq`` is a
gapless, 1-indexed append order (T2's autoincrement primary key), so every
leaf this index has ever seen is addressed by the same ``seq`` a caller
already gets back from ``append()``/``scan()`` -- no separate id scheme.
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from agent_action_capsule import VerificationResult

from asg_ledger.ledger.api import LedgerAPI, ScanQuery
from asg_ledger.ledger.records import ChainGap, LedgerRecord

from . import core
from .store import MemoryNodeStore

__all__ = ["MmrLedger", "RangeProof", "verify_range"]


@dataclass(frozen=True)
class RangeProof:
    """Proves a contiguous leaf range ``[from_seq, to_seq]`` (inclusive,
    1-indexed ledger seq) belongs to the MMR of the given ``size``.

    Composed from inclusion proofs of the two range boundaries, per the
    task's own suggested shape, rather than one proof per leaf in the range:
    a valid MMR size is only ever a *complete* accounting of exactly
    ``leaf_count(size)`` leaves (``core.peaks`` rejects any size that would
    represent a partial/sparse tree), so proving both boundary leaves are
    genuinely bound to their claimed digests under one common,
    peaks()-validated root also certifies every leaf strictly between them is
    structurally present -- there is no MMR-valid way for a size to "skip" an
    interior leaf position. ``size`` doubles as the peak-bagging logic the
    task asks for: it is fixed to ``node_count(to_seq)``, i.e. the MMR
    exactly as it stood right after ``to_seq`` was appended, so the range
    proof is meaningful even when the ledger has since grown further (see
    ``MmrLedger.consistency_proof`` for bridging an older range forward to a
    newer root).
    """

    from_seq: int
    to_seq: int
    size: int
    inclusion_from: core.InclusionProof
    inclusion_to: core.InclusionProof


def verify_range(
    root: bytes,
    from_seq: int,
    to_seq: int,
    from_digest: bytes,
    to_digest: bytes,
    proof: RangeProof,
) -> bool:
    """Pure range verification. No reader, never raises."""
    try:
        if proof is None or proof.from_seq != from_seq or proof.to_seq != to_seq:
            return False
        if from_seq < 1 or to_seq < from_seq:
            return False
        if core.leaf_count(proof.size) != to_seq:
            return False
        if not core.verify_inclusion(root, proof.size, from_seq - 1, from_digest, proof.inclusion_from):
            return False
        if not core.verify_inclusion(root, proof.size, to_seq - 1, to_digest, proof.inclusion_to):
            return False
        return True
    except Exception:
        return False


class MmrLedger:
    """MMR-backed inclusion/range-proof index over any ``LedgerAPI`` binding."""

    def __init__(self, ledger: LedgerAPI, *, node_store: core.NodeAppender | None = None) -> None:
        self._ledger = ledger
        self._nodes: core.NodeAppender = node_store if node_store is not None else MemoryNodeStore()
        self._body_digests: list[bytes] = []  # index i = leaf_index i's body_digest (== capsule_id bytes)

    # -- LedgerAPI passthrough (never reaches around it) ---------------------

    def append(self, capsule: dict, *, consequential: bool = True) -> LedgerRecord:
        record = self._ledger.append(capsule, consequential=consequential)
        self._index_record(record)
        return record

    def scan(self, query: ScanQuery | None = None) -> Iterator[LedgerRecord]:
        return self._ledger.scan(query)

    def fetch(self, capsule_id: str) -> LedgerRecord | None:
        return self._ledger.fetch(capsule_id)

    def verify(self, capsule_id: str) -> VerificationResult | None:
        return self._ledger.verify(capsule_id)

    def find_gaps(self) -> list[ChainGap]:
        return self._ledger.find_gaps()

    # -- MMR sync -------------------------------------------------------------

    def sync(self) -> int:
        """Fold any ledger records not yet indexed into the MMR.

        Returns the number of leaves newly added. Idempotent -- safe to call
        repeatedly, including with nothing new to add.
        """
        added = 0
        for record in self._ledger.scan():
            if record.seq <= len(self._body_digests):
                continue
            self._index_record(record)
            added += 1
        return added

    def _index_record(self, record: LedgerRecord) -> None:
        expected_seq = len(self._body_digests) + 1
        if record.seq != expected_seq:
            raise core.IntegrityError(
                f"cannot index record seq={record.seq} out of order "
                f"(expected seq={expected_seq}) -- MMR indexing requires a "
                "gapless, seq-ordered ledger"
            )
        body_digest = bytes.fromhex(record.capsule_id)
        core.add_leaf(self._nodes, core.leaf_hash(body_digest))
        self._body_digests.append(body_digest)

    # -- read surface -----------------------------------------------------

    def size(self) -> int:
        """Current MMR node count."""
        return self._nodes.size()

    def leaf_count(self) -> int:
        """Current number of indexed leaves."""
        return len(self._body_digests)

    def root(self) -> bytes:
        size = self._nodes.size()
        pks = core.peaks(size)
        peak_hashes = [self._nodes.node(p) for p in pks]
        return core.root_from_peaks(peak_hashes)

    def body_digest(self, seq: int) -> bytes:
        if seq < 1 or seq > len(self._body_digests):
            raise core.IntegrityError(f"no indexed leaf for seq {seq}")
        return self._body_digests[seq - 1]

    def inclusion_proof(self, seq: int, *, size: int | None = None) -> core.InclusionProof:
        """Inclusion proof for ledger record `seq`, against the MMR at `size`
        (defaults to the current size)."""
        target_size = size if size is not None else self._nodes.size()
        return core.inclusion_proof(self._nodes, seq - 1, target_size)

    def range_proof(self, from_seq: int, to_seq: int) -> RangeProof:
        """Range proof for the contiguous ledger records [from_seq, to_seq],
        against the MMR exactly as it stood when `to_seq` was appended."""
        if from_seq < 1 or to_seq < from_seq:
            raise core.InvalidArgumentError(f"invalid range [{from_seq}, {to_seq}]")
        size = core.node_count(to_seq)
        inclusion_from = core.inclusion_proof(self._nodes, from_seq - 1, size)
        inclusion_to = core.inclusion_proof(self._nodes, to_seq - 1, size)
        return RangeProof(from_seq, to_seq, size, inclusion_from, inclusion_to)

    def consistency_proof(self, size_a: int, size_b: int | None = None) -> core.ConsistencyProof:
        """Proof that the MMR at `size_b` (defaults to current size) extends
        the MMR at `size_a` -- the update path for a proof/root pinned at an
        earlier size, without recomputing anything about its leaves."""
        target_size_b = size_b if size_b is not None else self._nodes.size()
        return core.consistency_proof(self._nodes, size_a, target_size_b)
