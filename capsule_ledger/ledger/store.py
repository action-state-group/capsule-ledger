# SPDX-License-Identifier: Apache-2.0
"""Append-only capsule store: JSONL segments (source of truth) + a SQLite index.

The SQLite index is a derived, rebuildable structure (see :meth:`LedgerStore.reindex`)
that exists only to make :meth:`LedgerStore.scan` fast — the JSONL segments are the
durable record. This module is the *only* place in the package that is allowed to
touch ``sqlite3``: the connection is a private attribute and is never returned to a
caller, so every other subpackage must go through :class:`LedgerStore`.

Field mapping note: the ``agent-action-capsule`` envelope has no literal
``counterparty`` field. ``scan(agent=...)`` matches the capsule's ``developer``
field and ``scan(counterparty=...)`` matches ``operator`` — the closest available
mapping. Flagged as an open question in STATUS.md rather than guessed silently.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

try:  # POSIX only; the in-process binding targets POSIX (Linux CI, macOS dev).
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback, no cross-process lock
    fcntl = None  # type: ignore[assignment]

from agent_action_capsule import Finding, VerificationResult, compute_capsule_id
from agent_action_capsule import verify as _verify_capsule

from ..guards.revocation import build_key_timeline, check_time_fenced_revocation
from .api import LedgerAPI, ScanQuery
from .records import ChainGap, LedgerRecord

__all__ = ["LedgerStore"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    seq INTEGER PRIMARY KEY,
    capsule_id TEXT NOT NULL UNIQUE,
    segment TEXT NOT NULL,
    byte_offset INTEGER NOT NULL,
    timestamp TEXT,
    operator TEXT,
    developer TEXT,
    action_type TEXT,
    verdict_class TEXT,
    parent_capsule_id TEXT,
    chain_relation TEXT,
    consequential INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_records_timestamp ON records(timestamp);
CREATE INDEX IF NOT EXISTS idx_records_operator ON records(operator);
CREATE INDEX IF NOT EXISTS idx_records_developer ON records(developer);
CREATE INDEX IF NOT EXISTS idx_records_action_type ON records(action_type);
CREATE INDEX IF NOT EXISTS idx_records_verdict_class ON records(verdict_class);
CREATE INDEX IF NOT EXISTS idx_records_parent ON records(parent_capsule_id);
"""

_DEFAULT_SEGMENT_MAX_RECORDS = 20_000

# How long a concurrent opener/writer waits on sqlite's own file lock before
# giving up with `database is locked`. Generous because the contended writes
# here are tiny (one row + a commit); a real stall means a wedged process, not
# ordinary contention.
_SQLITE_BUSY_TIMEOUT_MS = 30_000


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class LedgerStore(LedgerAPI):
    """An append-only ledger of capsules, backed by JSONL segments + a SQLite index.

    This is the v0 *in-process* binding of :class:`~capsule_ledger.ledger.api.LedgerAPI`
    — see that module for why every method here takes/returns only serializable
    shapes rather than exposing sqlite3 internals.
    """

    def __init__(self, root: str | os.PathLike, *, segment_max_records: int = _DEFAULT_SEGMENT_MAX_RECORDS):
        self._root = Path(root)
        self._segments_dir = self._root / "segments"
        self._segments_dir.mkdir(parents=True, exist_ok=True)
        self._segment_max_records = segment_max_records

        # Every method that touches self._conn / self._write_fh / self._open_fhs
        # takes this lock — a per-scope caller (holds/scope.py's ScopeLocks) may
        # legitimately call into this store from multiple threads concurrently
        # for *different* scopes, and sqlite3 connections + shared file handles
        # are not otherwise safe under that. check_same_thread=False because the
        # lock, not thread affinity, is what makes this safe.
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self._root / "index.sqlite3", check_same_thread=False)
        # busy_timeout: when a *second process* opens this same on-disk ledger
        # concurrently (the ephemeral-mode shape — many short-lived callers, one
        # ledger directory), the WAL-mode pragma and the first index write race
        # on sqlite's own file lock. Without a busy timeout that surfaces as a
        # hard `database is locked` at construction; with it, the loser waits out
        # the winner's brief write. This is physical sqlite safety, distinct from
        # the business-atomicity serialization `serialize()` adds below.
        self._conn.execute(f"PRAGMA busy_timeout={_SQLITE_BUSY_TIMEOUT_MS}")
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

        # Cross-process append serialization. `self._lock` (a threading.RLock)
        # only serializes threads *within one process*; it cannot serialize two
        # separate processes sharing this directory. `serialize()` (below) takes
        # an OS-level advisory lock on this file, which the kernel enforces
        # across every process on the host, so a caller can hold a
        # read→decide→append span atomic against both threads AND processes.
        self._serialize_lock_path = self._root / "write.lock"
        self._serialize_lock_path.touch(exist_ok=True)

        self._write_fh = None
        self._write_segment_name = None
        self._open_fhs: dict[str, Any] = {}
        self._sync_write_segment()

    @property
    def root(self) -> Path:
        """This store's own directory -- the one legitimate anchor for
        colocated local-only artifacts that must never be confused with an
        imported fixture's throwaway tempdir (e.g. ``payload_store.py``'s
        resolve-at-read store, rooted at ``root / "payloads"``)."""
        return self._root

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        for fh in self._open_fhs.values():
            fh.close()
        self._open_fhs.clear()
        self._write_fh = None
        self._conn.close()

    def __enter__(self) -> LedgerStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- segment bookkeeping ------------------------------------------------

    def _existing_segments(self) -> list[str]:
        return sorted(p.name for p in self._segments_dir.glob("seg-*.jsonl"))

    def _segment_record_count(self, name: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM records WHERE segment = ?", (name,)
        ).fetchone()
        return row[0] if row else 0

    def _sync_write_segment(self) -> None:
        """Point the active write handle at the newest segment, rotating if full."""
        segments = self._existing_segments()
        if not segments or self._segment_record_count(segments[-1]) >= self._segment_max_records:
            next_index = len(segments) + 1
            name = f"seg-{next_index:06d}.jsonl"
            (self._segments_dir / name).touch()
        else:
            name = segments[-1]

        if self._write_segment_name != name:
            self._write_segment_name = name
            self._write_fh = self._get_fh(name, mode="a")

    def _get_fh(self, segment: str, *, mode: str = "rb"):
        # Binary mode: byte offsets from tell() must be true byte offsets so a
        # handle opened separately from the writer can seek to them reliably —
        # text-mode tell() cookies aren't guaranteed to be simple byte offsets.
        key = f"{segment}:{mode}"
        fh = self._open_fhs.get(key)
        if fh is None:
            fh = open(self._segments_dir / segment, mode)
            self._open_fhs[key] = fh
        return fh

    # -- write path -----------------------------------------------------

    @contextmanager
    def serialize(self) -> Iterator[None]:
        """Hold a single-writer critical section over this ledger, ACROSS
        threads and processes, for the duration of the ``with`` block.

        ``append`` already serializes each *physical* write through
        ``self._lock`` — that prevents torn writes and index corruption but
        says nothing about *business* atomicity: a caller that reads the
        ledger, decides "under cap", and only then appends can be interleaved
        by another caller doing the same, so both read the pre-write state and
        both append (``guards/engine.py``'s ``check()`` caps/dedupe span). A
        caller wraps that whole read→decide→append span in ``serialize()`` and
        the second caller's read then sees the first caller's append.

        Two layers, because ``self._lock`` (a ``threading.RLock``) is
        per-process and an ``fcntl`` lock is per-open-file-description:

        * the in-process ``RLock`` serializes threads sharing this one store;
        * an exclusive ``fcntl.flock`` on ``<root>/write.lock`` serializes
          separate processes sharing this directory (the ephemeral-mode shape:
          a container per request against one ledger).

        The file lock is advisory and released by the kernel if the holder
        dies, so a crashed caller never wedges the ledger permanently. On a
        platform without ``fcntl`` (Windows) only the in-process layer applies
        — flagged, not silently degraded: the in-process binding targets POSIX.
        """
        with self._lock:
            if fcntl is None:
                yield
                return
            lock_fh = open(self._serialize_lock_path, "a+")
            try:
                fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
            finally:
                lock_fh.close()

    def append(self, capsule: dict, *, consequential: bool = True) -> LedgerRecord:
        """Append a sealed capsule dict. Fsyncs the segment when ``consequential``.

        ``consequential`` defaults to ``True`` — unclassified writes default to
        consequential (per the gating decisions); classification itself is a
        guard-layer concern, not this store's.
        """
        capsule_id = capsule.get("capsule_id") or compute_capsule_id(capsule)

        with self._lock:
            self._sync_write_segment()
            fh = self._write_fh
            offset = fh.tell()
            line = json.dumps(capsule, separators=(",", ":"))
            fh.write(line + "\n")
            fh.flush()
            if consequential:
                os.fsync(fh.fileno())

            chain = capsule.get("chain") or {}
            disposition = capsule.get("disposition") or {}
            self._conn.execute(
                "INSERT INTO records (capsule_id, segment, byte_offset, timestamp, operator, "
                "developer, action_type, verdict_class, parent_capsule_id, chain_relation, consequential) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    capsule_id,
                    self._write_segment_name,
                    offset,
                    capsule.get("timestamp"),
                    capsule.get("operator"),
                    capsule.get("developer"),
                    capsule.get("action_type"),
                    disposition.get("verdict_class"),
                    chain.get("parent_capsule_id"),
                    chain.get("relation"),
                    1 if consequential else 0,
                ),
            )
            self._conn.commit()

            seq = self._conn.execute(
                "SELECT seq FROM records WHERE capsule_id = ?", (capsule_id,)
            ).fetchone()[0]
            return LedgerRecord(
                seq=seq,
                capsule_id=capsule_id,
                capsule=capsule,
                segment=self._write_segment_name,
                consequential=consequential,
            )

    def import_jsonl(self, path: str | os.PathLike, *, consequential: bool = False) -> int:
        """Append every record from an external JSONL file, in file order.

        Used to bring an existing ledger (e.g. one emitted by capsule-emit) into
        this store. Defaults to non-consequential since these are historical,
        already-durable records, not new consequential actions.
        """
        count = 0
        with open(path, encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                self.append(json.loads(line), consequential=consequential)
                count += 1
        return count

    def reindex(self) -> None:
        """Rebuild the SQLite index from the JSONL segments on disk.

        The segments are the source of truth; the index is a derived cache.
        """
        with self._lock:
            self._conn.execute("DELETE FROM records")
            self._conn.commit()
            for segment in self._existing_segments():
                fh = self._get_fh(segment, mode="r")
                fh.seek(0)
                offset = 0
                for raw in fh:
                    capsule = json.loads(raw)
                    capsule_id = capsule.get("capsule_id") or compute_capsule_id(capsule)
                    chain = capsule.get("chain") or {}
                    disposition = capsule.get("disposition") or {}
                    self._conn.execute(
                        "INSERT INTO records (capsule_id, segment, byte_offset, timestamp, operator, "
                        "developer, action_type, verdict_class, parent_capsule_id, chain_relation, consequential) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            capsule_id, segment, offset, capsule.get("timestamp"), capsule.get("operator"),
                            capsule.get("developer"), capsule.get("action_type"),
                            disposition.get("verdict_class"), chain.get("parent_capsule_id"),
                            chain.get("relation"), 1,
                        ),
                    )
                    offset += len(raw.encode("utf-8"))
            self._conn.commit()

    # -- read path --------------------------------------------------------

    def _row_to_record(self, row: sqlite3.Row) -> LedgerRecord:
        fh = self._get_fh(row["segment"], mode="r")
        fh.seek(row["byte_offset"])
        line = fh.readline()
        capsule = json.loads(line)
        return LedgerRecord(
            seq=row["seq"],
            capsule_id=row["capsule_id"],
            capsule=capsule,
            segment=row["segment"],
            consequential=bool(row["consequential"]),
        )

    def scan(self, query: ScanQuery | None = None) -> Iterator[LedgerRecord]:
        """Filtered scan over the ledger, ordered by append sequence.

        See :class:`~capsule_ledger.ledger.api.ScanQuery` for field semantics.
        """
        if query is None:
            query = ScanQuery()

        # The query + row materialization happen entirely under the lock, then
        # this generator yields from a plain list — holding the store lock
        # across caller-controlled iteration (which may pause indefinitely
        # between `next()` calls) would let one slow consumer block every
        # other thread's access to the store.
        with self._lock:
            self._conn.row_factory = sqlite3.Row
            clauses: list[str] = []
            params: list[Any] = []
            if query.agent is not None:
                clauses.append("developer = ?")
                params.append(query.agent)
            if query.counterparty is not None:
                clauses.append("operator = ?")
                params.append(query.counterparty)
            if query.verdict is not None:
                clauses.append("verdict_class = ?")
                params.append(query.verdict)
            if query.action_type is not None:
                clauses.append("action_type = ?")
                params.append(query.action_type)
            if query.since is not None:
                clauses.append("timestamp >= ?")
                params.append(query.since)
            if query.until is not None:
                clauses.append("timestamp <= ?")
                params.append(query.until)

            sql = "SELECT * FROM records"
            if clauses:
                sql += " WHERE " + " AND ".join(clauses)
            sql += " ORDER BY seq"
            if query.limit is not None:
                sql += " LIMIT ?"
                params.append(query.limit)

            cur = self._conn.execute(sql, params)
            records = [self._row_to_record(row) for row in cur]
            self._conn.row_factory = None
        yield from records

    def fetch(self, capsule_id: str) -> LedgerRecord | None:
        """Fetch a single record by exact ``capsule_id`` or an unambiguous prefix."""
        with self._lock:
            self._conn.row_factory = sqlite3.Row
            row = self._conn.execute(
                "SELECT * FROM records WHERE capsule_id = ?", (capsule_id,)
            ).fetchone()
            if row is None:
                row = self._conn.execute(
                    "SELECT * FROM records WHERE capsule_id LIKE ? ORDER BY seq LIMIT 1",
                    (capsule_id + "%",),
                ).fetchone()
            self._conn.row_factory = None
            if row is None:
                return None
            return self._row_to_record(row)

    def verify(self, capsule_id: str) -> VerificationResult | None:
        """``agent_action_capsule.verify`` for a stored capsule, plus this
        store's own time-fenced key-revocation check (`guards/revocation.py`)
        layered on top.

        The reference verifier is spec-level and payload-only — it has no
        notion of this package's local signing keys or their rotation
        history (see that module's own docstring). Rebuilding the key
        timeline from this ledger's own ``key_rotation`` events and checking
        this capsule's claimed key_id/timestamp against it is store-level
        context, the same category as the parent-existence check below.
        """
        with self._lock:
            record = self.fetch(capsule_id)
            if record is None:
                return None
            all_ids = [r[0] for r in self._conn.execute("SELECT capsule_id FROM records")]
            result = _verify_capsule(record.capsule, store=all_ids)

            timeline = build_key_timeline(self)
            revocation = check_time_fenced_revocation(record.capsule, timeline)
            if not revocation.ok:
                result.findings.append(Finding("key_revoked_at_timestamp", revocation.reason, severity="error"))
                result.ok = False

            return result

    # -- chain-gap detection ------------------------------------------------

    def find_gaps(self) -> list[ChainGap]:
        """Locate every ``chain.parent_capsule_id`` reference not found in the ledger.

        Each gap is a browsable window bounded by the ledger-position neighbors of
        the break (``edge_before``/``edge_after``), never a silent null.
        """
        with self._lock:
            self._conn.row_factory = sqlite3.Row
            rows = self._conn.execute(
                "SELECT * FROM records WHERE parent_capsule_id IS NOT NULL ORDER BY seq"
            ).fetchall()
            gaps: list[ChainGap] = []
            for row in rows:
                parent_id = row["parent_capsule_id"]
                exists = self._conn.execute(
                    "SELECT 1 FROM records WHERE capsule_id = ?", (parent_id,)
                ).fetchone()
                if exists is not None:
                    continue

                child = self._row_to_record(row)
                edge_before = None
                if row["seq"] > 1:
                    before_row = self._conn.execute(
                        "SELECT * FROM records WHERE seq = ?", (row["seq"] - 1,)
                    ).fetchone()
                    if before_row is not None:
                        edge_before = self._row_to_record(before_row)

                duration = None
                if edge_before is not None:
                    t_before = _parse_ts(edge_before.capsule.get("timestamp"))
                    t_after = _parse_ts(child.capsule.get("timestamp"))
                    if t_before is not None and t_after is not None:
                        duration = (t_after - t_before).total_seconds()

                before_label = f"#{edge_before.seq}" if edge_before is not None else "⊥"
                window = f"{before_label} → #{child.seq}"

                gaps.append(
                    ChainGap(
                        missing_parent_id=parent_id,
                        child=child,
                        relation=row["chain_relation"],
                        edge_before=edge_before,
                        edge_after=child,
                        window=window,
                        duration_seconds=duration,
                        browsable_from_either_edge=True,
                    )
                )
            self._conn.row_factory = None
            return gaps
