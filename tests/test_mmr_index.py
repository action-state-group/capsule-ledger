"""MmrLedger wired to a real LedgerAPI (LedgerStore): append/sync, inclusion
and range proofs over real capsule data, and the MMR stability property
across appends -- the whole point of this data structure over a naive
Merkle tree, per the task's own acceptance gate.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from asg_ledger.ledger import LedgerStore
from asg_ledger.mmr import core
from asg_ledger.mmr.index import MmrLedger, verify_range

FIXTURES = Path(__file__).parent / "fixtures"
AMAURY = FIXTURES / "amaury_sample_ledger.jsonl"


def _fixture_lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _synthetic_capsule(i: int) -> dict:
    return {
        "capsule_id": None,  # computed by LedgerStore.append via compute_capsule_id
        "operator": "acme",
        "developer": "agent-x",
        "action_type": "decide",
        "timestamp": f"2026-01-01T00:00:{i:02d}Z",
        "disposition": {"verdict_class": "executed"},
        "seq_marker": i,
    }


def _capsule_without_id(i: int) -> dict:
    cap = _synthetic_capsule(i)
    del cap["capsule_id"]
    return cap


@pytest.fixture
def store(tmp_path):
    s = LedgerStore(tmp_path)
    yield s
    s.close()


# -- append wiring + sync --------------------------------------------------


def test_append_through_wrapper_indexes_immediately(store):
    mmr = MmrLedger(store)
    for i in range(5):
        mmr.append(_capsule_without_id(i), consequential=False)
    assert mmr.leaf_count() == 5
    assert mmr.size() == core.node_count(5)
    # root is non-trivial (not the empty-MMR root)
    assert mmr.root() != core.root_from_peaks([])


def test_sync_catches_up_a_ledger_populated_without_the_wrapper(store):
    for i in range(6):
        store.append(_capsule_without_id(i), consequential=False)

    mmr = MmrLedger(store)
    assert mmr.leaf_count() == 0  # nothing indexed yet -- append() was never used
    added = mmr.sync()
    assert added == 6
    assert mmr.leaf_count() == 6

    # idempotent: calling sync() again adds nothing
    assert mmr.sync() == 0
    assert mmr.leaf_count() == 6


def test_sync_and_append_produce_the_same_root_for_the_same_leaves(store, tmp_path):
    capsules = [_capsule_without_id(i) for i in range(9)]

    store_a = LedgerStore(tmp_path / "a")
    mmr_a = MmrLedger(store_a)
    for cap in capsules:
        mmr_a.append(copy.deepcopy(cap), consequential=False)
    root_a = mmr_a.root()
    store_a.close()

    store_b = LedgerStore(tmp_path / "b")
    for cap in capsules:
        store_b.append(copy.deepcopy(cap), consequential=False)
    mmr_b = MmrLedger(store_b)
    mmr_b.sync()
    root_b = mmr_b.root()
    store_b.close()

    assert root_a == root_b


def test_mmr_ledger_delegates_scan_fetch_find_gaps(store):
    mmr = MmrLedger(store)
    original = _fixture_lines(AMAURY)
    n = store.import_jsonl(AMAURY)
    assert n == len(original)
    mmr.sync()
    assert mmr.leaf_count() == len(original)

    scanned = list(mmr.scan())
    assert len(scanned) == len(original)
    fetched = mmr.fetch(original[0]["capsule_id"])
    assert fetched is not None
    assert mmr.find_gaps() == []  # amaury fixture is gap-free (matches test_ledger_store.py)


# -- inclusion proofs over real capsule data ---------------------------------


def test_inclusion_proof_round_trips_over_real_capsule_ledger(store):
    mmr = MmrLedger(store)
    n = store.import_jsonl(AMAURY)
    mmr.sync()
    assert mmr.leaf_count() == n

    root = mmr.root()
    size = mmr.size()
    for seq in range(1, n + 1):
        proof = mmr.inclusion_proof(seq)
        bd = mmr.body_digest(seq)
        assert core.verify_inclusion(root, size, seq - 1, bd, proof)


def test_inclusion_proof_rejects_tampered_body_digest(store):
    mmr = MmrLedger(store)
    store.import_jsonl(AMAURY)
    mmr.sync()

    root = mmr.root()
    size = mmr.size()
    seq = 3
    proof = mmr.inclusion_proof(seq)
    bd = bytearray(mmr.body_digest(seq))
    bd[0] ^= 0xFF
    assert not core.verify_inclusion(root, size, seq - 1, bytes(bd), proof)
    # untampered digest still verifies -- confirms the rejection above is real,
    # not a proof that never verifies at all
    assert core.verify_inclusion(root, size, seq - 1, mmr.body_digest(seq), proof)


# -- range proofs -----------------------------------------------------------


def test_range_proof_round_trips_over_real_capsule_ledger(store):
    mmr = MmrLedger(store)
    n = store.import_jsonl(AMAURY)
    mmr.sync()

    from_seq, to_seq = 2, min(n, 5)
    proof = mmr.range_proof(from_seq, to_seq)
    root = mmr.root()
    from_digest = mmr.body_digest(from_seq)
    to_digest = mmr.body_digest(to_seq)
    assert verify_range(root, from_seq, to_seq, from_digest, to_digest, proof)


def test_range_proof_rejects_tampered_boundary_digest(store):
    mmr = MmrLedger(store)
    n = store.import_jsonl(AMAURY)
    mmr.sync()

    from_seq, to_seq = 1, min(n, 4)
    proof = mmr.range_proof(from_seq, to_seq)
    root = mmr.root()
    from_digest = mmr.body_digest(from_seq)
    to_digest = mmr.body_digest(to_seq)
    assert verify_range(root, from_seq, to_seq, from_digest, to_digest, proof)

    tampered = bytearray(to_digest)
    tampered[0] ^= 0xFF
    assert not verify_range(root, from_seq, to_seq, from_digest, bytes(tampered), proof)


# -- stability across appends: the whole point of an MMR ---------------------


def test_inclusion_proof_stability_across_appends(store):
    """Take an inclusion proof for ledger record seq=3 after 7 appends, then
    append 3 more (seq 8-10). The original proof/root pair must verify
    forever, unmodified -- and a cheap consistency (range-bridging) proof,
    built only from already-stored peak hashes plus a few new nodes, must
    extend trust to the new root without recomputing anything about leaf 3.

    Note on the literal task wording ("original proof still verifies against
    the NEW root without modification"): for a real MMR this is only true
    when the leaf's containing peak never gets absorbed into a taller
    mountain by later appends. Here (leaf 3 of 7, then +3 more leaves) it
    *does* get absorbed -- asserted explicitly below via `core.peaks`, so
    this isn't glossed over. The witness path a verifier needs to reach a
    *new* peak necessarily grows by one hop in that case; no MMR design
    avoids this, since the bagged root itself changes on every append. The
    property that actually makes MMR worth using over a naive tree -- and
    which this test proves for real -- is that the OLD peak node bytes
    (pos 6 below) are never recomputed/rewritten, the OLD proof against the
    OLD root needs no modification ever, and extending trust to a NEW root
    costs one small consistency proof over already-immutable data, never a
    full tree rebuild.
    """
    for i in range(7):
        store.append(_capsule_without_id(i), consequential=False)

    mmr = MmrLedger(store)
    mmr.sync()
    assert mmr.leaf_count() == 7

    old_size = mmr.size()
    old_root = mmr.root()
    seq = 3  # leaf_index = 2
    old_proof = mmr.inclusion_proof(seq, size=old_size)
    old_body_digest = mmr.body_digest(seq)

    # sanity: the containing peak for leaf_index=2 at size=7 is pos 6.
    assert core.peaks(old_size) == [6, 9, 10]
    old_peak_bytes_before = mmr._nodes.node(6)  # noqa: SLF001 -- test-only introspection

    assert core.verify_inclusion(old_root, old_size, seq - 1, old_body_digest, old_proof)

    for i in range(7, 10):
        store.append(_capsule_without_id(i), consequential=False)
    mmr.sync()
    assert mmr.leaf_count() == 10

    new_size = mmr.size()
    new_root = mmr.root()
    assert new_size != old_size
    assert new_root != old_root

    # 1) old peak's containing mountain has grown (pos 6 is no longer itself
    #    a peak) -- confirming this isn't a trivial no-op scenario.
    assert 6 not in core.peaks(new_size)

    # 2) but the OLD peak's own hash bytes were never rewritten: reading
    #    position 6 again returns byte-identical content to before the append.
    old_peak_bytes_after = mmr._nodes.node(6)  # noqa: SLF001
    assert old_peak_bytes_after == old_peak_bytes_before

    # 3) the ORIGINAL proof against the ORIGINAL root still verifies,
    #    completely unmodified -- it never needed touching.
    assert core.verify_inclusion(old_root, old_size, seq - 1, old_body_digest, old_proof)

    # 4) trust is extended to the new root via a consistency proof built
    #    only from the (already-stored, unmodified) old peaks plus a few new
    #    interior nodes -- no recomputation of leaf 3's own inclusion path.
    bridge = mmr.consistency_proof(old_size, new_size)
    assert core.verify_consistency(old_root, old_size, new_root, new_size, bridge)

    # composition: (old_proof verifies against old_root) AND (old_root is
    # consistent with new_root) together certify "leaf 3 is included in the
    # size-10 ledger" without ever rehashing anything about leaf 3.


def test_range_proof_stability_across_appends(store):
    """Same property, for a range: a range proof taken while the ledger had
    7 leaves stays valid against its own (frozen) size/root forever, and a
    consistency proof bridges it to a later, larger root."""
    for i in range(7):
        store.append(_capsule_without_id(i), consequential=False)
    mmr = MmrLedger(store)
    mmr.sync()

    old_range = mmr.range_proof(2, 5)
    old_size = old_range.size
    old_root_at_size = mmr.consistency_proof(old_size, old_size)  # trivial, just to fetch peaks cheaply
    assert old_root_at_size.old_peaks == old_root_at_size.new_peaks

    from_digest = mmr.body_digest(2)
    to_digest = mmr.body_digest(5)
    root_at_old_size = core.root_from_peaks([mmr._nodes.node(p) for p in core.peaks(old_size)])  # noqa: SLF001
    assert verify_range(root_at_old_size, 2, 5, from_digest, to_digest, old_range)

    for i in range(7, 10):
        store.append(_capsule_without_id(i), consequential=False)
    mmr.sync()

    new_size = mmr.size()
    new_root = mmr.root()

    # the old range proof still verifies against its own frozen size/root
    assert verify_range(root_at_old_size, 2, 5, from_digest, to_digest, old_range)

    # bridged forward to the new root without touching the range proof itself
    bridge = mmr.consistency_proof(old_size, new_size)
    assert core.verify_consistency(root_at_old_size, old_size, new_root, new_size, bridge)
