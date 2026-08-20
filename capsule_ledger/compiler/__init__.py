# SPDX-License-Identifier: Apache-2.0
"""The outcome compiler: one declaration, compiled forward into a check and
backward into a report, bound by a sealed compilation record (design of
record: ``compiler-and-setup-design-2026-08-19.md`` §2 -- private, but §2-§4
are written to lift into public docs once G-IP1 clears; this package
implements the mechanism, not the publication).

Phase 1 shipped the schema surface: vocabulary (verdict-pair enums,
``response_class``, refusal reason codes, re-derivability grades -- all
with display strings), and the sealed-capsule shapes for the objects that
cannot be retrofitted once history seals: the compilation record ``C``,
the scope-census attestation, and refusal capsules.

Phase 2 (``compile.py``) is the dual compiler itself: ``compile_declaration``
takes a ``Declaration`` (D) and produces ``P`` (a real ``PlanDefinition``,
wired into the existing ``plan_containment`` machinery) and ``F`` (a real
``FoldDefinition``), sealed together as C via ``seal_compilation_record``;
``verify_compilation_record`` is the drift check that makes C more than
decoration. ``precondition.py`` is the closed v0 precondition vocabulary
with published, two-sided conformance vectors. ``cedar.py`` is the Cedar
interop boundary (import a policy's digest, export the
authorization-shaped subset) -- an interop target, never substrate.
"""
from __future__ import annotations
