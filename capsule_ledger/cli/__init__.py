# SPDX-License-Identifier: Apache-2.0
"""``capsule_ledger.cli`` package root.

``main`` is resolved lazily (PEP 562 module ``__getattr__``) rather than
imported eagerly at package-init time. ``main.py`` pulls in every verb
submodule (``agents_cmd``, ``fold_cmds``, etc.), some of which depend on
subpackages that are product-side and live outside this package for
consumers that only need one leaf submodule (e.g. ``ledger_io``'s
``open_ledger``/``require_ledger_path`` helpers, which capsule-engine's own
CLI imports directly) -- ``import capsule_ledger.cli.ledger_io`` must not
have to succeed at importing the whole verb set to do that.

Importing the ``.main`` submodule below has a name collision to guard
against: Python's import system always binds an imported submodule onto its
parent package (``sys.modules['capsule_ledger.cli'].main = <the main.py
module>``) as an unconditional side effect, regardless of this function's
own return value. Left alone, that side effect shadows the ``main``
*function* the next time anything reads ``capsule_ledger.cli.main`` --
``from capsule_ledger.cli import main`` would silently bind the caller to
the submodule object instead of the entry point. Overwriting the module
namespace after extracting the function corrects the binding back.
"""
from typing import Any

__all__ = ["main"]


def __getattr__(name: str) -> Any:
    if name == "main":
        from .main import main as _main

        globals()["main"] = _main
        return _main
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
