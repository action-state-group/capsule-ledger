# SPDX-License-Identifier: Apache-2.0
"""Re-derivability grade (design §2.3): labels whether a check's verdict is
independently re-derivable from sealed inputs alone (``pure_replay``), or
depends on a fold over ledger state no capsule carries
(``ledger_state_dependent``).

``plan_containment`` is a pure function of (action, plan) -- no
``LedgerAPI`` parameter, no scan -- so its inputs are sealed and a stranger
holding the compiled plan can recompute its verdict exactly.
``caps``/``dedupe``/``verify_before_dispatch`` all take ``ledger:
LedgerAPI`` and scan; re-deriving their verdicts means possessing the
ledger and adopting this repo's own ledger semantics, not just the plan.
Neither is a defect -- they prove different things -- but conflating them
is the exact "asymmetry discovered is an embarrassment" the design warns
against. ``grade_for_check`` is the seeded default a pack author consults
when declaring an obligation's grade; nothing in this module writes the
grade onto an already-emitted ``ConstraintRecord`` -- that is additive,
opt-in wiring for the checks that need it, not a retrofit of every
existing decision capsule this repo has already sealed.
"""
from __future__ import annotations

from .vocabulary import RE_DERIVABILITY_GRADES

__all__ = ["RE_DERIVABILITY_GRADES", "grade_for_check", "UnknownCheckType"]

# Purity is the admission test (design §2.3 / [ldg-containment-replay-carveout]).
_GRADE_BY_CHECK: dict[str, str] = {
    "plan_containment": "pure_replay",
    "caps": "ledger_state_dependent",
    "dedupe": "ledger_state_dependent",
    "verify_before_dispatch": "ledger_state_dependent",
}


class UnknownCheckType(ValueError):
    """``check`` has no seeded default grade -- callers must supply
    ``re_derivability_grade`` explicitly rather than rely on a guess."""


def grade_for_check(check: str) -> str:
    try:
        grade = _GRADE_BY_CHECK[check]
    except KeyError as exc:
        raise UnknownCheckType(
            f"no seeded re-derivability grade for check {check!r} -- declare "
            f"re_derivability_grade explicitly (one of {sorted(RE_DERIVABILITY_GRADES)})"
        ) from exc
    assert grade in RE_DERIVABILITY_GRADES  # keeps this table and the closed set from drifting apart
    return grade
