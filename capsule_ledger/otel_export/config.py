# SPDX-License-Identifier: Apache-2.0
"""``ExporterConfig``: endpoint, headers, sampling, on/off -- read from env by
default, same ``CAPSULE_LEDGER_*``-falls-back-to-``ASG_LEDGER_*`` pattern as
the rest of the codebase (``envcompat.env_get``). No custom transport, no
bespoke protocol: the endpoint/headers/protocol fields map directly onto the
standard OTLP exporter constructor arguments, nothing more.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..envcompat import env_get

__all__ = ["ExporterConfig"]


def _parse_headers(raw: str | None) -> dict[str, str]:
    """``key1=value1,key2=value2`` -- the same format ``OTEL_EXPORTER_OTLP_HEADERS``
    uses upstream, so an operator's existing OTel env config drops in as-is."""
    if not raw:
        return {}
    headers: dict[str, str] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair:
            continue
        key, _, value = pair.partition("=")
        headers[key.strip()] = value.strip()
    return headers


def _parse_bool(raw: str | None, default: bool) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


@dataclass(frozen=True)
class ExporterConfig:
    """``endpoint is None`` means "no OTLP collector configured" -- the
    exporter degrades to a no-op for spans in that case (never an error);
    use ``JSONLDecisionExporter`` for the always-works fallback target
    instead when there's no collector to point at."""

    enabled: bool = True
    endpoint: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    sampling_ratio: float = 1.0
    protocol: str = "http"  # "http" | "grpc"
    service_name: str = "capsule-ledger"
    jsonl_path: str | None = None

    def __post_init__(self) -> None:
        if self.protocol not in {"http", "grpc"}:
            raise ValueError(f"protocol must be 'http' or 'grpc', got {self.protocol!r}")
        if not 0.0 <= self.sampling_ratio <= 1.0:
            raise ValueError(f"sampling_ratio must be in [0.0, 1.0], got {self.sampling_ratio!r}")

    @classmethod
    def from_env(cls) -> ExporterConfig:
        enabled = _parse_bool(env_get("CAPSULE_LEDGER_OTEL_ENABLED", "ASG_LEDGER_OTEL_ENABLED"), True)
        endpoint = env_get("CAPSULE_LEDGER_OTEL_ENDPOINT", "ASG_LEDGER_OTEL_ENDPOINT")
        headers = _parse_headers(env_get("CAPSULE_LEDGER_OTEL_HEADERS", "ASG_LEDGER_OTEL_HEADERS"))
        sampling_raw = env_get("CAPSULE_LEDGER_OTEL_SAMPLING_RATIO", "ASG_LEDGER_OTEL_SAMPLING_RATIO", "1.0")
        protocol = env_get("CAPSULE_LEDGER_OTEL_PROTOCOL", "ASG_LEDGER_OTEL_PROTOCOL", "http")
        service_name = env_get("CAPSULE_LEDGER_OTEL_SERVICE_NAME", "ASG_LEDGER_OTEL_SERVICE_NAME", "capsule-ledger")
        jsonl_path = env_get("CAPSULE_LEDGER_OTEL_JSONL_PATH", "ASG_LEDGER_OTEL_JSONL_PATH")
        return cls(
            enabled=enabled,
            endpoint=endpoint,
            headers=headers,
            sampling_ratio=float(sampling_raw),
            protocol=protocol or "http",
            service_name=service_name or "capsule-ledger",
            jsonl_path=jsonl_path,
        )
