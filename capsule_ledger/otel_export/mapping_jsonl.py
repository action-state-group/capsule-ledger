# SPDX-License-Identifier: Apache-2.0
"""Plain JSON lines mapping -- the FALLBACK target. No collector, no schema
registry, no upstream stability to depend on: this is this package's own
``DecisionEvent.to_attributes()`` shape, one JSON object per line. It always
works and costs nothing, which is the entire reason it exists as a distinct,
always-available target alongside the two that depend on external schemas.
"""
from __future__ import annotations

import json

from .event import DecisionEvent

__all__ = ["to_jsonl_record", "to_jsonl_line"]


def to_jsonl_record(event: DecisionEvent) -> dict[str, str | int]:
    return event.to_attributes()


def to_jsonl_line(event: DecisionEvent) -> str:
    return json.dumps(to_jsonl_record(event), sort_keys=True)
