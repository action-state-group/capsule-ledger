# SPDX-License-Identifier: Apache-2.0
"""RESOLVE-AT-READ: a local, content-addressed store of raw payloads the
reader legitimately holds (ldg-registry-driven-viewer item 5).

The ledger record stays commitments-only, always -- a capsule only ever
carries ``constraints[].evidence_digest`` / ``disposition.reason_digest``
(64-hex JSON-DIGESTs, see ``agent_action_capsule.contracts``), never the raw
evidence/reason object itself (``guards/capsule.py``'s own docstring: "never
stored raw on the capsule"). This store is where a reader who separately,
legitimately holds one of those preimages (their own audit log, their own
guard's in-memory evidence before it was digested away) can deliberately
keep a local copy so the CLI/console can resolve it back onto the digest at
display time -- disclose-and-recompute, never silent trust: every read
re-digests the stored content and compares, so a corrupted or tampered local
copy fails loudly rather than rendering unverified content as if it matched.

Deliberately NOT wired into capsule sealing (``guards/capsule.py``) or
export (``cli/bundle_cmd.py``) -- populating this store is always a
separate, deliberate act (``capsule payload put``), and nothing here is ever
read by the export path. A capsule's own digest commitment is unaffected by
whether a matching payload happens to sit in this store.

Rooted at ``<ledger_root>/payloads/`` -- a sibling of the ledger's own
``segments/``/``index.sqlite3`` (``ledger/store.py``). Tying the store to a
real ``LedgerStore`` directory (never to an imported JSONL fixture's
throwaway tempdir, ``cli/ledger_io.py``'s ``open_ledger()``) is what makes
"local, standalone-grade ledger" checkable by construction: a foreign bundle
or an imported fixture never gets an auto-resolve, because there is no
persistent directory to hold one.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_action_capsule import json_digest

__all__ = ["PayloadStore", "ResolvedPayload"]

_SUBDIR = "payloads"


@dataclass(frozen=True)
class ResolvedPayload:
    """One resolve-at-read result. ``match`` is computed, never stored --
    the whole point is that it is recomputed live on every render, not
    cached trust in a previous check."""

    digest: str
    content: Any
    recomputed_digest: str

    @property
    def match(self) -> bool:
        return self.recomputed_digest == self.digest


class PayloadStore:
    """One ledger's local resolve-at-read store, rooted at
    ``<ledger_root>/payloads/``. Never created implicitly -- ``exists`` is
    ``False`` until the reader deliberately calls :meth:`put` (or the
    directory is created by hand), which is exactly the gate ``show``/`log`/
    the console use to decide whether auto-resolve applies at all."""

    def __init__(self, ledger_root: str | Path):
        self._dir = Path(ledger_root) / _SUBDIR

    @property
    def exists(self) -> bool:
        return self._dir.is_dir()

    def put(self, payload: Any) -> str:
        """Store *payload*, keyed by its own JSON-DIGEST. Returns the digest
        so the caller can confirm it against the capsule field they expect
        this to resolve (``evidence_digest``/``reason_digest``)."""
        digest = json_digest(payload)
        self._dir.mkdir(parents=True, exist_ok=True)
        (self._dir / f"{digest}.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return digest

    def resolve(self, digest: str | None) -> ResolvedPayload | None:
        """``None`` when nothing is stored under *digest* -- the common
        case, and not an error: most digests on most capsules will have no
        locally-held preimage. When a file IS present, its content is
        re-digested live; a mismatch (local corruption/tampering) is
        returned, not hidden -- callers render that as a loud failure, never
        a silent pass-through."""
        if not digest or not self.exists:
            return None
        path = self._dir / f"{digest}.json"
        if not path.is_file():
            return None
        content = json.loads(path.read_text(encoding="utf-8"))
        return ResolvedPayload(digest=digest, content=content, recomputed_digest=json_digest(content))
