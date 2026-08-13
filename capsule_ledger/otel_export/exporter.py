# SPDX-License-Identifier: Apache-2.0
"""OTLP span export (primary) and a plain-JSON-lines fallback exporter,
implementing the scope's "span per mediated action; decision as span
attributes; receipt digest as a first-class attribute."

**Graceful degradation is the load-bearing property here (AARM R8
acceptance): exporter failure never blocks or alters a decision.** Both
exporter classes below never raise out of ``export()`` -- setup failures,
network failures, and serialization failures are all caught, logged once at
``WARNING``, and swallowed. A telemetry outage degrades to "no telemetry
this call", never to "no decision" or "a different decision". Callers should
treat export as fire-and-forget, invoked *after* the guard has already
produced (and, in the enforcing path, appended) its decision -- never awaited
as a precondition for dispatch.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from .config import ExporterConfig
from .event import DecisionEvent
from .mapping_genai import to_genai_attributes
from .mapping_jsonl import to_jsonl_record

logger = logging.getLogger(__name__)

__all__ = ["DecisionExporter", "JSONLDecisionExporter"]


def _build_span_exporter(config: ExporterConfig):
    if config.protocol == "grpc":
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    else:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    return OTLPSpanExporter(endpoint=config.endpoint, headers=config.headers)


class DecisionExporter:
    """OTLP/``gen_ai`` span exporter -- the PRIMARY target. Owns a
    ``TracerProvider``; construct one per process, not per decision.

    Pass ``span_exporter`` explicitly (e.g. an in-memory exporter) for
    tests -- that is the only supported seam; there is no bespoke transport
    to configure around it.
    """

    def __init__(self, config: ExporterConfig | None = None, *, span_exporter=None) -> None:
        self._config = config or ExporterConfig.from_env()
        self._tracer = None
        if not self._config.enabled:
            return
        try:
            exporter = span_exporter if span_exporter is not None else self._build_default_exporter()
            if exporter is None:
                return
            self._tracer = self._build_tracer(exporter)
        except Exception:
            logger.warning("otel exporter setup failed; telemetry export disabled for this process", exc_info=True)
            self._tracer = None

    def _build_default_exporter(self):
        if not self._config.endpoint:
            return None
        return _build_span_exporter(self._config)

    def _build_tracer(self, span_exporter):
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

        provider = TracerProvider(
            resource=Resource.create({"service.name": self._config.service_name}),
            sampler=ParentBased(TraceIdRatioBased(self._config.sampling_ratio)),
        )
        provider.add_span_processor(SimpleSpanProcessor(span_exporter))
        return provider.get_tracer("capsule_ledger.otel_export")

    def export(self, event: DecisionEvent | None) -> bool:
        """Export one decision event as a span. Returns whether a span was
        actually recorded -- never raises. ``event is None`` (the guard's
        no-capsule-minted paths -- see ``event.decision_event_from_guard_decision``)
        and "exporter disabled/unconfigured" are both silent, ordinary
        no-ops, not errors."""
        if event is None or self._tracer is None:
            return False
        try:
            attributes = to_genai_attributes(event)
            with self._tracer.start_as_current_span(event.action_verb, attributes=attributes):
                pass
            return True
        except Exception:
            logger.warning("otel span export failed; decision was not affected", exc_info=True)
            return False


class JSONLDecisionExporter:
    """The FALLBACK target: append-only local JSON lines, no collector, no
    schema dependency -- always works. Same never-raises contract as
    ``DecisionExporter``."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def export(self, event: DecisionEvent | None) -> bool:
        if event is None:
            return False
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(to_jsonl_record(event), sort_keys=True) + "\n")
            return True
        except OSError:
            logger.warning("jsonl telemetry export failed; decision was not affected", exc_info=True)
            return False
