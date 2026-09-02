# SPDX-License-Identifier: Apache-2.0
"""Module alias -- ``capsule_ledger.ledger.admission`` IS ``cll.ledger.admission``.

Graduated to the ``checkpointed-local-log`` repo's ``cll`` package per the
W3.1 CLL extraction (2026-09-01, action-state-strategy/docs/strategy/
w3-ledger-dissolution-lib-per-spec-2026-09-01.md). True alias (``sys.modules``
substitution), not a name-copying re-export, so any caller reaching this
module via either import path sees the identical object -- see
``capsule_ledger/ledger/store.py`` for the one module in this package that
is NOT a pure alias (it subclasses to layer this repo's own key-revocation
check back on).
"""
import sys

from cll.ledger import admission as _admission

sys.modules[__name__] = _admission
