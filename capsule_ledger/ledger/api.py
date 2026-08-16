# SPDX-License-Identifier: Apache-2.0
"""Transport-agnostic ledger interface.

:class:`~capsule_ledger.ledger.store.LedgerStore` is the v0 *in-process* binding of
this interface. Every method here takes and returns only plain, serializable
shapes — dataclasses of primitives, dicts, and other dataclasses — never file
handles, cursors, or a raw ``sqlite3`` connection. That's deliberate: the
ephemeral-mode deployment (gating decisions doc §3 — a Lambda/Cloud Run/short-
lived container calling a nearby ledger service over a local network hop) needs
a binding that talks to a remote ledger service instead of a local directory.
Because every request/response here is already serializable, that binding can
implement this same ``LedgerAPI`` Protocol by putting these shapes on the wire
(e.g. as JSON) — no API change, no caller-visible difference between the two.

Nothing is built for that remote binding yet — this module only keeps the v0
API from being painted into an in-process-only corner.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from agent_action_capsule import VerificationResult

from .records import ChainGap, LedgerRecord

__all__ = ["ScanQuery", "LedgerAPI", "serialize_writes"]


@dataclass(frozen=True)
class ScanQuery:
    """A filtered-scan request. Every field is optional and independently serializable.

    ``agent`` matches the capsule's ``developer`` field; ``counterparty`` matches
    ``operator`` (the closest available mapping — the envelope has no literal
    ``counterparty`` field). ``since``/``until`` are inclusive ISO-8601 bounds on
    ``timestamp``; ``verdict`` matches ``disposition.verdict_class``.
    """

    agent: str | None = None
    since: str | None = None
    until: str | None = None
    counterparty: str | None = None
    verdict: str | None = None
    action_type: str | None = None
    limit: int | None = None


@runtime_checkable
class LedgerAPI(Protocol):
    """The read/append surface every ledger binding (in-process or remote) implements."""

    def append(self, capsule: dict, *, consequential: bool = True) -> LedgerRecord: ...

    def scan(self, query: ScanQuery | None = None) -> Iterator[LedgerRecord]: ...

    def fetch(self, capsule_id: str) -> LedgerRecord | None: ...

    def verify(self, capsule_id: str) -> VerificationResult | None: ...

    def find_gaps(self) -> list[ChainGap]: ...

    def serialize(self) -> AbstractContextManager[None]:
        """Single-writer critical section over the ledger, across threads AND
        processes, for the duration of the ``with`` block. A caller wraps a
        read→decide→append span in it so a second caller's read cannot race
        ahead of this one's append. See ``LedgerStore.serialize`` for the v0
        in-process implementation; a remote binding implements the same
        contract with whatever its backend provides (a row lock, a lease, a
        sequencer). ``serialize_writes(ledger)`` is the safe accessor for
        callers that must work against a binding predating this method.
        """
        ...


def serialize_writes(ledger: LedgerAPI) -> AbstractContextManager[None]:
    """Return ``ledger.serialize()`` if the binding provides it, else a no-op.

    The cap/dedupe race fix (``guards/engine.py``) depends on holding a
    read→decide→append span atomic across processes. A binding that predates
    ``serialize`` (or a lightweight test double) is not itself cross-process
    contended, so falling back to a ``nullcontext`` is correct for it — it is
    NOT a silent weakening of the real ``LedgerStore``, which does implement
    ``serialize``. Using this accessor rather than ``getattr`` at every call
    site keeps that reasoning in one place.
    """
    serialize = getattr(ledger, "serialize", None)
    if serialize is None:
        return nullcontext()
    return serialize()
