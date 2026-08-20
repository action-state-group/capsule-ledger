# SPDX-License-Identifier: Apache-2.0
"""The outcome compiler: one declaration, compiled forward into a check and
backward into a report, bound by a sealed compilation record (design of
record: ``compiler-and-setup-design-2026-08-19.md`` §2 -- private, but §2-§4
are written to lift into public docs once G-IP1 clears; this package
implements the mechanism, not the publication).

Phase 1 (this package's initial scope) ships the schema surface only:
vocabulary (verdict-pair enums, ``response_class``, refusal reason codes,
re-derivability grades -- all with display strings), and the sealed-capsule
shapes for the objects that cannot be retrofitted once history seals: the
compilation record ``C``, the scope-census attestation, and refusal
capsules. Compiling an actual declaration into ``P``/``F`` is Phase 2.
"""
from __future__ import annotations
