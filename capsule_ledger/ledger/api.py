# SPDX-License-Identifier: Apache-2.0
"""Module alias -- ``capsule_ledger.ledger.api`` IS ``cll.ledger.api``.
See ``capsule_ledger/ledger/admission.py`` for why.
"""
import sys

from cll.ledger import api as _api

sys.modules[__name__] = _api
