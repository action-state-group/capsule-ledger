# SPDX-License-Identifier: Apache-2.0
"""Module alias -- ``capsule_ledger.ledger.records`` IS ``cll.ledger.records``.
See ``capsule_ledger/ledger/admission.py`` for why.
"""
import sys

from cll.ledger import records as _records

sys.modules[__name__] = _records
