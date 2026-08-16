# SPDX-License-Identifier: Apache-2.0
"""``LedgerStore.serialize()``: the cross-process single-writer critical
section the [ldg-guardengine-caps-race] fix is built on.

These tests exercise the storage-layer primitive directly, separately from
the engine that uses it, so a regression in the lock itself is caught close
to the cause. The engine-level proof (that ``GuardEngine.check()`` actually
holds this across its read->decide->append span) lives in
``test_engine_caps_race_multiprocess.py`` and ``test_pack_differential_concurrency.py``.
"""
from __future__ import annotations

import multiprocessing as mp
import tempfile
import time

from capsule_ledger.ledger import LedgerStore


def _process_context():
    # fork where available (fast), else spawn. See
    # test_engine_caps_race_multiprocess.py for why forkserver was rejected and
    # why the fork DeprecationWarning is a false alarm for these workers.
    for method in ("fork", "spawn"):
        try:
            return mp.get_context(method)
        except ValueError:  # pragma: no cover
            continue
    return mp.get_context()  # pragma: no cover


_MP = _process_context()

_HOLD_S = 0.15


def _holder(ledger_dir: str, barrier, q, name: str) -> None:
    """Open an independent store on the shared dir, take serialize(), hold it
    briefly, and report the [enter, exit] wall-clock window."""
    store = LedgerStore(ledger_dir)
    try:
        barrier.wait(timeout=30)
        with store.serialize():
            enter = time.monotonic()
            time.sleep(_HOLD_S)
            q.put((name, enter, time.monotonic()))
    finally:
        store.close()


def test_serialize_is_mutually_exclusive_across_processes():
    """Two processes, each taking serialize() on the same on-disk ledger, must
    not overlap: the second's critical section starts only after the first's
    ends. This is the property an in-process threading.Lock CANNOT provide and
    the fcntl file lock does -- the whole reason the fix serializes at the
    storage layer rather than in the engine."""
    with tempfile.TemporaryDirectory() as ledger_dir:
        LedgerStore(ledger_dir).close()  # materialize the dir + lock file
        barrier = _MP.Barrier(2)
        q: mp.Queue = _MP.Queue()
        procs = [_MP.Process(target=_holder, args=(ledger_dir, barrier, q, n)) for n in ("A", "B")]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=60)
        windows = sorted((q.get(timeout=5) for _ in range(2)), key=lambda w: w[1])

    (_, a_enter, a_exit), (_, b_enter, b_exit) = windows
    # The later-entering critical section must begin no earlier than the
    # earlier one ended (allowing a tiny scheduling slop well under the hold).
    assert b_enter >= a_exit - 0.01, (
        f"serialize() critical sections overlapped across processes: "
        f"A=[{a_enter:.3f},{a_exit:.3f}] B=[{b_enter:.3f},{b_exit:.3f}] -- the cross-process file "
        "lock is not mutually excluding, so a read->decide->append span held under it is not atomic "
        "across processes"
    )


def _appender(ledger_dir: str, barrier, q, name: str, n: int) -> None:
    """Under serialize(), read the current count, then append one record. If
    serialize() truly excludes the sibling, no two appends interleave, so the
    counts each worker reads-before-append are distinct and monotone."""
    store = LedgerStore(ledger_dir)
    try:
        barrier.wait(timeout=30)
        seen = []
        for _ in range(n):
            with store.serialize():
                before = sum(1 for _ in store.scan())
                store.append(
                    {"capsule_id": f"{name}-{before}-{time.time_ns()}", "developer": "d",
                     "timestamp": "2026-08-11T09:00:00Z"},
                    consequential=True,
                )
                seen.append(before)
        q.put((name, seen))
    finally:
        store.close()


def test_serialize_gives_a_consistent_read_before_write_across_processes():
    """Two processes each do N (read-count, append) steps under serialize().
    With a correct cross-process lock every append is globally ordered, so the
    union of the counts both workers read-before-append is exactly
    {0,1,...,2N-1} with no duplicates -- each worker saw a distinct, already-
    committed prefix. A missing/parallel lock produces duplicate read counts
    (two workers both read the same 'before')."""
    n = 8
    with tempfile.TemporaryDirectory() as ledger_dir:
        LedgerStore(ledger_dir).close()
        barrier = _MP.Barrier(2)
        q: mp.Queue = _MP.Queue()
        procs = [_MP.Process(target=_appender, args=(ledger_dir, barrier, q, name, n))
                 for name in ("A", "B")]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=60)
        results = dict(q.get(timeout=5) for _ in range(2))

    all_before = sorted(results["A"] + results["B"])
    assert all_before == list(range(2 * n)), (
        f"read-before-append counts were not a clean 0..{2 * n - 1} sequence: {all_before} "
        f"(A={results['A']}, B={results['B']}) -- appends interleaved, so serialize() did not give "
        "each writer an atomic read->append across processes"
    )
