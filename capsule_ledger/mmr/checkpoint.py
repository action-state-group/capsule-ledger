# SPDX-License-Identifier: Apache-2.0
"""Module alias -- ``capsule_ledger.mmr.checkpoint`` IS ``cll.ledger.checkpoint``.

Graduated to the ``checkpointed-local-log`` repo's ``cll`` package per the
W3.1 CLL extraction (2026-09-01, action-state-strategy/docs/strategy/
w3-ledger-dissolution-lib-per-spec-2026-09-01.md). True alias (``sys.modules``
substitution), not a name-copying re-export -- tests and call sites
monkeypatch module-level attributes here (e.g. ``DEFAULT_TS_URL``) and
expect the real functions in ``cll.ledger.checkpoint`` to observe the
patch, which is only true when both names resolve to the same module
object (see ``capsule_ledger/ledger/admission.py`` for the same pattern,
and ``cll/ledger/checkpoint.py``'s own docstring for why this is a
DISTINCT protocol from ``cll.checkpoint.emit``, not a duplicate of it).
"""
import sys

from cll.ledger import checkpoint as _checkpoint

sys.modules[__name__] = _checkpoint
