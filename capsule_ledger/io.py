# SPDX-License-Identifier: Apache-2.0
"""Public ledger-I/O surface for callers outside this repo (compiler, judge,
engine): opening a ledger from a CLI-style path argument, resolving
``--ledger``/``$CAPSULE_LEDGER``, and the env-var read shim. ``cli.ledger_io``
and ``envcompat`` are internal plumbing the CLI's own sub-commands share --
``cli/__init__.py`` deliberately restricts its own ``__all__`` to ``main``, so
those two modules are not meant to be reached into directly from another
repo. Import from here instead."""
from __future__ import annotations

from .cli.ledger_io import open_ledger, require_ledger_path
from .envcompat import env_get

__all__ = ["open_ledger", "require_ledger_path", "env_get"]
