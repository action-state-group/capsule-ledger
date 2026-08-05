"""Append-only ledger store and the read/query API other subpackages use.

``LedgerAPI`` (api.py) is the transport-agnostic interface; ``LedgerStore``
(store.py) is its v0 in-process binding. Everything else in the package must
go through ``LedgerStore`` — it is the only module allowed to touch sqlite3.
"""
from .api import LedgerAPI, ScanQuery
from .records import ChainGap, LedgerRecord
from .store import LedgerStore

__all__ = ["LedgerAPI", "ScanQuery", "LedgerRecord", "ChainGap", "LedgerStore"]
