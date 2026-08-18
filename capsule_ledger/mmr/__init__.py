# SPDX-License-Identifier: Apache-2.0
"""Merkle Mountain Range (MMR): the local ledger's inclusion/range-proof structure.

``core.py`` is the pure algorithm (position math, domain-separated hashing,
inclusion/consistency proofs, no I/O). ``store.py`` is the v0 in-memory node
backing. ``index.py`` wires the MMR to T2's ``LedgerAPI`` (append/scan/fetch/
find_gaps) -- the MMR never reaches around that interface into raw storage.
"""
from .core import (
    ConsistencyProof,
    InclusionProof,
    IntegrityError,
    InvalidArgumentError,
    add_leaf,
    consistency_proof,
    height_at,
    interior_hash,
    leaf_count,
    leaf_hash,
    leaf_index_to_pos,
    node_count,
    peaks,
    pos_to_leaf_index,
    root_from_peaks,
    verify_consistency,
    verify_inclusion,
)
from .index import MmrLedger, RangeProof, verify_range
from .store import MemoryNodeStore

__all__ = [
    "ConsistencyProof",
    "InclusionProof",
    "IntegrityError",
    "InvalidArgumentError",
    "add_leaf",
    "consistency_proof",
    "height_at",
    "interior_hash",
    "leaf_count",
    "leaf_hash",
    "leaf_index_to_pos",
    "node_count",
    "peaks",
    "pos_to_leaf_index",
    "root_from_peaks",
    "verify_consistency",
    "verify_inclusion",
    "MmrLedger",
    "RangeProof",
    "verify_range",
    "MemoryNodeStore",
]
