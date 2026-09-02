# SPDX-License-Identifier: Apache-2.0
"""Module alias -- ``capsule_ledger.ledger.store`` IS ``cll.ledger.store``.
See ``capsule_ledger/ledger/admission.py`` for why.

**No longer a subclass (#126 fix, 2026-09-02).** The W3.1 extraction
originally made this module a thin subclass that layered this repo's own
time-fenced key-revocation check (``ledger/revocation.py``) onto
``verify()`` via the ``extra_findings`` seam, on the theory that ``cll``
itself must not depend on guard/policy-layer product code. The
2026-09-01 dependency-trace ruling ([w3-engine-residual-moves]) reclassified
that check as a verify-primitive, not guard/policy code, and ported it into
``cll.revocation`` -- ``cll.ledger.store.LedgerStore.verify`` now runs it as
a DEFAULT finding, zero caller configuration required (cll
``cll-revocation-default-finding``). Keeping this repo's own copy of the
same check wired in on top via ``extra_findings`` would have run revocation
TWICE per ``verify()`` call, from two copies that can drift out of sync --
this module is now a pure alias like its siblings and inherits cll's
default instead. ``extra_findings`` on the base class remains available
for a caller's OWN additional store-level checks; it is an extension
point, not the delivery mechanism for revocation.
"""
import sys

from cll.ledger import store as _store

sys.modules[__name__] = _store
