# SPDX-License-Identifier: Apache-2.0
"""Action-class convention labels (ldg-registry-driven-viewer item 2):
where a capsule's ``asg_payload.action_class`` matches a registered
convention, every display surface shows its human label/description from
this module instead of a hardcoded string.

**Scope note ([ldg-ledger-scope-re-extraction] RESIDUALS pass §3.1):** this
is a MINIMAL, self-contained shim -- capsule-ledger's own core read/verify
display surface (``cli/format.py``, its sole consumer now that ``console/``
is deleted) needs only ``describe_action_class``. The full vendored CPB +
provisional-field-value registry (``describe_field_value``,
``conventions_digest``, the ``cpb_registry.json`` live tables) moved to
capsule-engine as the interim vendor-of-record (§3.1(a)) -- this module
never imports capsule-engine and carries its own tiny label table, so the
two are independent, not two forks of one truth.

``action_class`` -- not the -02 spec's own closed ``action_type`` field
(restricted to ``fyi``/``decide``, see ``guards/action.py``) -- is the
namespaced convention field the "Agent Action Semantics" layer
(``payment.*``, ``comms.*``, ``authority.*``, ``hold.*``) actually governs
(registry-architecture-and-namespace-2026-08-10.md §1, Home 2, table 4).
That table's real home, ``capsule-registry``, is confirmed not to exist yet
(created "at the capsule-ledger flip", same doc §6 item 5) -- the identical
situation ``packs/pins.py`` already solved for pack/fold digest pins. This
module is the lookup GATE, deliberately decoupled from where the convention
data came from: today it's a local, vendored snapshot (``conventions.json``,
shipped as package data, no network call ever -- this package's own
no-network-calls discipline); swapping in a live ``capsule-registry`` fetch
later changes *how the table is obtained*, never this module's callers.

**The never-reject invariant** (same as the spec-level REGISTRY.md already
documents for ``verdict_class`` etc.): an ``action_class`` with no entry
here renders as-is, marked unregistered -- informational only, never an
error. A capsule carrying no ``action_class`` at all is a different,
legitimate state (most capsules predate any pack) and is never described as
"unregistered".
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Any

__all__ = ["ActionConvention", "describe_action_class"]


@dataclass(frozen=True)
class ActionConvention:
    action_class: str | None
    label: str
    description: str | None
    registered: bool


def _load_raw() -> dict[str, Any]:
    text = resources.files("capsule_ledger.registry").joinpath("conventions.json").read_text(encoding="utf-8")
    return json.loads(text)


@lru_cache(maxsize=1)
def _table() -> dict[str, Any]:
    return _load_raw().get("action_class_conventions", {})


def describe_action_class(action_class: str | None) -> ActionConvention:
    if not action_class:
        return ActionConvention(action_class=None, label="(no action class recorded)", description=None, registered=False)
    entry = _table().get(action_class)
    if entry is None:
        return ActionConvention(action_class=action_class, label=action_class, description=None, registered=False)
    return ActionConvention(
        action_class=action_class, label=entry["label"], description=entry.get("description"), registered=True
    )
