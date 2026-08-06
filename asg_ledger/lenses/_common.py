# SPDX-License-Identifier: Apache-2.0
"""Tiny shared helpers for the lens modules -- kept out of ``cli/`` deliberately
(lenses are core query-API logic; the CLI wraps them, never the reverse)."""
from __future__ import annotations

from datetime import datetime

__all__ = ["record_verb", "parse_timestamp"]


def record_verb(capsule: dict) -> str:
    """The verb portion of ``action_id`` (e.g. "approve_purchase"), falling
    back to ``action_type`` for records with no ``action_id``. Mirrors
    ``cli/format.py``'s ``summarize_action`` (duplicated, not imported, to
    keep this package's dependency direction one-way: cli -> lenses)."""
    action_id = capsule.get("action_id") or ""
    verb = action_id.split("/", 1)[0] if action_id else ""
    return verb or capsule.get("action_type") or "(unnamed action)"


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
