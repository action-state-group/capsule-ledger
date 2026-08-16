# SPDX-License-Identifier: Apache-2.0
"""Multi-process cap-enforcement test for ``GuardEngine.check()``.

This is the cross-process companion to
``test_pack_differential_concurrency.py``. That test uses two *threads*
sharing one in-process ``LedgerStore``; this one uses two real *processes*,
each opening its **own** ``LedgerStore`` (its own sqlite connection, its own
write file handle) on the **same on-disk ledger directory**.

Why a second, process-based test is not redundant: an in-process
``threading.Lock`` (e.g. ``holds/scope.py``'s ``ScopeLocks``) would make the
threaded test pass while a second worker *process* still reads pre-write
state and blows the cap -- a green test asserting a property the deployment
does not have. The serialization point therefore has to be the ledger append
itself (a cross-process file lock / atomic append-with-recheck), and only a
genuine multi-process race can prove that. Threads share the same lock
objects and the same file handles; processes share nothing but the files on
disk, which is the real deployment shape (multiple short-lived callers -- a
Lambda / Cloud Run container per request -- against one ledger).

Traffic shape mirrors the differential test exactly: two concurrent
submissions, each 60% of the cap, for the SAME ``(developer, action_class)``
window. Sequential execution admits exactly one; a correct engine must admit
at most one under concurrency too. The unfixed engine admits both.

Process economy: to stay fast and robust under ``spawn``/``forkserver`` (where
each process start re-imports the package), each test uses exactly TWO
long-lived worker processes that LOOP over all rounds, re-synchronising on a
per-round barrier, rather than spawning a fresh pair per round. The parent
creates a fresh ledger directory per round and hands the list to the workers,
so each round's contention is still isolated to that round's pair.
"""
from __future__ import annotations

import multiprocessing as mp
import tempfile
from pathlib import Path

from capsule_ledger.guards import Action, LocalSigner
from capsule_ledger.ledger import LedgerStore
from capsule_ledger.packs import build_engine, install_pack, load_pack_dir

PACK_DIR = Path(__file__).parent.parent / "capsule_ledger" / "packs" / "catalog" / "payments-safety"

OPERATOR = "acme-checkout"
DEVELOPER = "checkout-mp-probe@v1"
CAP_MINOR = 1_000_000
N_ROUNDS = 8


# Real separate PROCESSES, not threads: each worker has its OWN LedgerStore
# (own sqlite connection, own write handle), sharing nothing with its sibling
# but the files on disk. That is the whole point -- an in-process
# threading.Lock in one worker cannot serialize the other, so only a
# cross-process mechanism (the ledger's fcntl file lock) can make this pass.
#
# Start method: `fork` where available (fast -- no per-worker re-import of the
# package), else `spawn`. `fork` emits a DeprecationWarning about forking a
# possibly-multi-threaded process; that hazard only bites when the child
# touches a lock a parent thread held at fork time, and these workers construct
# every resource (LedgerStore, sqlite connection, engine) fresh in the child
# and inherit no such lock -- so it is a false alarm here. `forkserver` was
# tried and rejected: per-round re-import made it minutes-slow and barrier-flaky
# on this workload. All methods give genuinely independent processes with
# independent sqlite connections; the property under test depends only on the
# workers being real, separate processes.
def _process_context():
    for method in ("fork", "spawn"):
        try:
            return mp.get_context(method)
        except ValueError:  # pragma: no cover - method unavailable on this platform
            continue
    return mp.get_context()  # pragma: no cover


_MP = _process_context()


def _make_engine(ledger, project_dir):
    pack = load_pack_dir(PACK_DIR)
    installed = install_pack(pack, project_dir=project_dir, mode="observe")
    signer = LocalSigner(key_id="mp-probe-key", secret=b"mp-probe-fixed-key")
    return build_engine(installed, ledger=ledger, signer_provider=lambda: signer)


def _action_for(round_dir_developer: str, round_idx: int, letter: str, *, amount_frac: float,
                shared_target: bool) -> Action:
    # `shared_target=False` (caps test): each worker's action differs only by
    # target/action_id, so dedupe never fires and only the shared cap contends.
    # `shared_target=True` (dedupe test): the two actions are byte-identical, so
    # only dedupe can distinguish them. Both share a timestamp: the caps fold is
    # a rolling-window sum evaluated `as_of` the action's own timestamp, so
    # different timestamps would let one action fall outside the other's window
    # and mask the race with a windowing artifact rather than testing
    # serialization.
    tag = "same" if shared_target else letter
    return Action(
        verb="dispatch_payout", operator=OPERATOR, developer=round_dir_developer,
        action_class="money.transfer", amount_minor=int(CAP_MINOR * amount_frac), currency="EUR",
        target=f"vendor-mp-probe/mp-{round_idx}-{tag}",
        action_id=f"dispatch_payout/mp-probe-{round_idx}-{tag}",
        timestamp=f"2026-08-11T09:{round_idx:02d}:10Z",
    )


def _looping_worker(letter: str, rounds: list[tuple[str, str]], amount_frac: float,
                    shared_target: bool, barrier, result_q) -> None:
    """One long-lived process. For each round it opens a FRESH LedgerStore on
    that round's shared directory (a new sqlite connection + write handle each
    round, the real cross-process shape), re-synchronises with its sibling on
    the barrier, submits its action, and reports (round_idx, outcome). Looping
    in-process keeps the expensive process start to one per worker."""
    proj = tempfile.mkdtemp(prefix=f"mp-proj-{letter}-")
    for round_idx, (ledger_dir, developer) in enumerate(rounds):
        ledger = LedgerStore(ledger_dir)
        try:
            engine = _make_engine(ledger, proj)
            action = _action_for(developer, round_idx, letter, amount_frac=amount_frac,
                                  shared_target=shared_target)
            barrier.wait(timeout=60)
            decision = engine.check(action, dry_run=True)
            result_q.put((round_idx, decision.outcome))
        finally:
            ledger.close()


def _run_rounds(amount_frac: float, shared_target: bool) -> list[int]:
    """Drive N_ROUNDS of two contending processes; return admits-per-round."""
    tmpdirs = [tempfile.TemporaryDirectory() for _ in range(N_ROUNDS)]
    try:
        rounds = [(td.name, f"{DEVELOPER}-mp-{i}") for i, td in enumerate(tmpdirs)]
        barrier = _MP.Barrier(2)
        result_q: mp.Queue = _MP.Queue()
        procs = [
            _MP.Process(target=_looping_worker,
                        args=(letter, rounds, amount_frac, shared_target, barrier, result_q))
            for letter in ("a", "b")
        ]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=120)

        admits = [0] * N_ROUNDS
        seen = [0] * N_ROUNDS
        while not result_q.empty():
            round_idx, outcome = result_q.get()
            seen[round_idx] += 1
            if outcome == "allow":
                admits[round_idx] += 1
        # Every round must have produced two decisions -- a lost worker would
        # silently under-count admits and could hide the race.
        assert seen == [2] * N_ROUNDS, f"not every round ran two workers to completion: seen={seen}"
        return admits
    finally:
        for td in tmpdirs:
            td.cleanup()


def test_cap_holds_across_processes_on_shared_ledger():
    """The 40/40-vs-20/40 traffic shape, run across real processes.

    Each round: one shared on-disk ledger, two processes each submitting a
    60%-of-cap payment for the same developer window. A correct engine admits
    at most one per round (<= N_ROUNDS total); the unfixed engine admits both
    (== 2*N_ROUNDS). We assert the admitted total never exceeds what sequential
    execution would admit -- exactly the differential test's bar, but proven
    across processes rather than threads."""
    per_round_admits = _run_rounds(amount_frac=0.6, shared_target=False)
    concurrent_admits = sum(per_round_admits)

    assert sum(1 for a in per_round_admits if a >= 1) == N_ROUNDS, (
        f"some rounds admitted zero of two -- workers did not run to completion: {per_round_admits}"
    )
    max_admissible = N_ROUNDS  # sequential admits exactly one of each pair
    assert concurrent_admits <= max_admissible, (
        f"multi-process admission ({concurrent_admits}/{2 * N_ROUNDS}) exceeded the sequential "
        f"maximum ({max_admissible}/{2 * N_ROUNDS}) -- GuardEngine.check()'s read->decide->append "
        "span is not serialized across PROCESSES sharing one ledger. An in-process lock cannot fix "
        f"this. Per-round admits: {per_round_admits}"
    )


def test_dedupe_holds_across_processes_on_shared_ledger():
    """The same read->decide->append race, on the ``dedupe`` check instead of
    ``caps``. Two byte-identical concurrent actions across processes (same
    dedupe equivalence key), at a small amount well under the cap so ``caps``
    is never the gate. Exactly one is a new action; the other is a duplicate.
    A correct engine admits at most one per round: the loser's dedupe scan,
    inside the SAME ``serialize()`` span caps uses, sees the winner's append
    and denies it."""
    per_round_admits = _run_rounds(amount_frac=0.05, shared_target=True)
    concurrent_admits = sum(per_round_admits)

    assert sum(1 for a in per_round_admits if a >= 1) == N_ROUNDS, (
        f"some rounds admitted zero of two -- workers did not run to completion: {per_round_admits}"
    )
    assert concurrent_admits <= N_ROUNDS, (
        f"multi-process dedupe admission ({concurrent_admits}/{2 * N_ROUNDS}) exceeded the sequential "
        f"maximum ({N_ROUNDS}/{2 * N_ROUNDS}) -- the dedupe check's scan->append span is not serialized "
        f"across PROCESSES sharing one ledger. Per-round admits: {per_round_admits}"
    )
