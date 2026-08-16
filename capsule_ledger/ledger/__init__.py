# SPDX-License-Identifier: Apache-2.0
"""Append-only ledger store and the read/query API other subpackages use.

``LedgerAPI`` (api.py) is the transport-agnostic interface; ``LedgerStore``
(store.py) is its v0 in-process binding. Everything else in the package must
go through ``LedgerStore`` — it is the only module allowed to touch sqlite3.
"""
from .api import LedgerAPI, ScanQuery, serialize_writes
from .records import ChainGap, LedgerRecord
from .store import LedgerStore

__all__ = ["LedgerAPI", "ScanQuery", "serialize_writes", "LedgerRecord", "ChainGap", "LedgerStore"]
