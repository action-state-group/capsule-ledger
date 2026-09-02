# SPDX-License-Identifier: Apache-2.0
"""Public ledger-I/O surface for callers outside this repo (compiler, judge,
engine): opening a ledger from a CLI-style path argument, resolving
``--ledger``/``$CAPSULE_LEDGER``, the shared ``ScanQuery`` filter-flag set
every ledger-backed verb offers, and the env-var read shim. ``cli.ledger_io``
and ``envcompat`` are internal plumbing the CLI's own sub-commands share --
``cli/__init__.py`` deliberately restricts its own ``__all__`` to ``main``, so
those two modules are not meant to be reached into directly from another
repo. Import from here instead."""
from __future__ import annotations

from .cli.ledger_io import (
    add_scan_query_args,
    build_scan_query,
    echo_parts,
    open_ledger,
    require_ledger_path,
)
from .envcompat import env_get

__all__ = [
    "open_ledger",
    "require_ledger_path",
    "add_scan_query_args",
    "build_scan_query",
    "echo_parts",
    "env_get",
]
