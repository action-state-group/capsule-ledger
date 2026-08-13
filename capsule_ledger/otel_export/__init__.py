# SPDX-License-Identifier: Apache-2.0
"""AARM R8 telemetry export: OTLP export of guard decision events.

**The one design rule that matters (ldg-otel-exporter-aarm-r8): the
telemetry event carries a receipt REFERENCE, never a receipt COPY.** See
``event.py``'s ``DecisionEvent`` docstring for how that's enforced at the
type level, and ``docs/otel-export.md`` for the operator-facing summary.

Unrelated to ``capsule_ledger.telemetry`` (opt-in, aggregate-only product
usage metrics -- a different concept entirely; see that package's own
docstring). This package never touches that one and vice versa.
"""
from .config import ExporterConfig
from .event import (
    ALLOW,
    DECISION_VALUES,
    DEFER,
    DENY,
    MODIFY,
    STEP_UP,
    DecisionEvent,
    decision_event_from_guard_decision,
)
from .exporter import DecisionExporter, JSONLDecisionExporter

__all__ = [
    "ExporterConfig",
    "DecisionEvent",
    "decision_event_from_guard_decision",
    "ALLOW",
    "DENY",
    "MODIFY",
    "STEP_UP",
    "DEFER",
    "DECISION_VALUES",
    "DecisionExporter",
    "JSONLDecisionExporter",
]
