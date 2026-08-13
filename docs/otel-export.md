# OTel decision-event export (AARM R8)

**The telemetry event carries a receipt REFERENCE, never a receipt COPY.**
Every exported event points at a decision capsule already sealed and
appended to the ledger — it carries the digest, the decision, and enough
attributes to pivot on, and never the capsule payload itself. Two mutable
copies of the same fact is a divergence bug waiting to happen: if a SIEM
event ever disagreed with the receipt it points at, that disagreement would
manufacture the exact ambiguity the receipt exists to eliminate.

**The telemetry event is not evidence and MUST NOT be relied upon as such.**
It is best-effort, operator-controlled, and trivially forgeable — a lossy
index into the ledger, not a competing record of it. See
`agent-action-capsule`'s telemetry-binding profile for the normative version
of this statement.

This is a SHOULD (AARM R8), not a MUST: on by default only when an operator
configures an endpoint (`capsule_ledger.otel_export`), and its own failures
never affect a decision (see Graceful degradation below).

## Quick start

```python
from capsule_ledger.otel_export import DecisionExporter, ExporterConfig, decision_event_from_guard_decision

exporter = DecisionExporter(ExporterConfig.from_env())  # one per process

decision = engine.check(action)
event = decision_event_from_guard_decision(decision, action)
exporter.export(event)  # fire-and-forget, after the decision is already final
```

`decision_event_from_guard_decision` returns `None` when the guard produced
no capsule at all (its fail-closed no-capsule paths — signing key
unavailable, view unhealthy). `DecisionExporter.export(None)` is a silent
no-op; there is nothing to point at yet.

## Configuration

| Env var | Meaning | Default |
|---|---|---|
| `CAPSULE_LEDGER_OTEL_ENABLED` | on/off switch | `true` |
| `CAPSULE_LEDGER_OTEL_ENDPOINT` | OTLP collector endpoint; unset = span export is a no-op | unset |
| `CAPSULE_LEDGER_OTEL_HEADERS` | `key1=value1,key2=value2` (same format as `OTEL_EXPORTER_OTLP_HEADERS`) | none |
| `CAPSULE_LEDGER_OTEL_PROTOCOL` | `http` or `grpc` | `http` |
| `CAPSULE_LEDGER_OTEL_SAMPLING_RATIO` | `0.0`–`1.0`, trace-ID-ratio sampling | `1.0` |
| `CAPSULE_LEDGER_OTEL_SERVICE_NAME` | OTel resource `service.name` | `capsule-ledger` |
| `CAPSULE_LEDGER_OTEL_JSONL_PATH` | path for `JSONLDecisionExporter`, the always-works fallback target | unset |

(`ASG_LEDGER_OTEL_*` also read as a fallback, same rename pattern as the
rest of this package's env vars.) No custom transport, no bespoke protocol
— these map directly onto the standard `opentelemetry-exporter-otlp-proto-*`
constructor arguments.

## Attribute set

| Attribute | Required? | Meaning |
|---|---|---|
| `action.verb` | always | the action verb |
| `decision` | always | `ALLOW \| DENY \| MODIFY \| STEP_UP \| DEFER` |
| `receipt.digest` | always | the decision capsule's `capsule_id` — the pointer |
| `action.target` | optional | dedupe discriminator, when set |
| `manifest.digest` | optional | which policy manifest governed |
| `plan.digest` | optional | which compiled plan governed (`ldg-plan-containment`'s C1) |
| `outcome.id` | optional | the declared outcome this action serves |
| `plan.step_index` | optional | position in the compiled plan |
| `containment.result` | optional | `pass \| fail` (`ldg-plan-containment`'s C2) |
| `identity.human` / `.service` / `.agent` / `.session` | optional | caller-supplied identity facets |

Optional fields are **omitted, not null**, when absent — same pattern as
`asg_payload.manifest_digest` on the decision capsule itself.
`decision_event_from_guard_decision` maps `GuardEngine`'s own outcome
vocabulary (`allow`/`deny`/`escalate`) onto this one: `escalate` → `STEP_UP`
(routed to a human, awaiting resolution — not `DEFER`, which is a *human*-
elected postponement this guard has no path to produce). `plan.digest` and
`containment.result` are optional pass-through kwargs pending
`ldg-plan-containment` landing on `main` — this package does not block on
that branch.

## Target formats (priority order)

1. **OTLP / `gen_ai`** (`otel_export/mapping_genai.py`, `DecisionExporter`) — primary.
   `gen_ai.*` is experimental and actively moving upstream (the entire
   convention set was deprecated out of the main semantic-conventions repo
   on 2026-06-12 into a dedicated one with no tagged release yet) — every
   `gen_ai.*` attribute name is isolated to this one file so a rename
   upstream touches nothing else in this package.
2. **OCSF** (`otel_export/mapping_ocsf.py`) — secondary, best-effort. There
   is no ratified OCSF class for AI-agent activity; this maps onto the
   closest existing one (Detection Finding, `class_uid` 2004) and documents
   the mismatch honestly in the module — do not treat the mapping as a
   first-class fit. Not built into `DecisionExporter`'s default OTLP path;
   call `to_ocsf_finding(event)` directly for an OCSF-shaped record.
3. **Plain JSON lines** (`otel_export/mapping_jsonl.py`, `JSONLDecisionExporter`) —
   fallback. No collector, no schema dependency, always works.

## Graceful degradation

Exporter failure never blocks or alters a decision. Both `DecisionExporter`
and `JSONLDecisionExporter` catch every exception inside `export()` and
`__init__`, log a warning, and return `False` — they never raise. A
telemetry outage degrades to "no telemetry this call," never to "no
decision" or "a different decision." Export is always fire-and-forget,
called *after* the guard has already decided (and, on the enforcing path,
already appended) — never awaited as a precondition for dispatch.

## Spec status

Not in `agent-action-capsule` core — the receipt is the normative artifact;
telemetry is a projection of it, and naming OTLP/OCSF in core would inherit
their release cycles. See `agent-action-capsule`'s telemetry-binding profile
document for the cross-repo, spec-facing version of the rules above.
