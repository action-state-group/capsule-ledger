# SPDX-License-Identifier: Apache-2.0
"""Minimal, self-contained action-class label lookup -- see ``conventions.py``.
The full vendored CPB registry moved to capsule-engine
([ldg-ledger-scope-re-extraction] RESIDUALS pass §3.1)."""
from __future__ import annotations

from .conventions import ActionConvention, describe_action_class

__all__ = [
    "ActionConvention",
    "describe_action_class",
]
