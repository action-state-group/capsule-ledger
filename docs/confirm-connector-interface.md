# Confirm-ingester: the external-system confirmation pattern

A commitment your agent made (an intent capsule, a hold reservation, any
capsule with an `capsule_id`) often only really finishes when a *third
system* says so: an IdP flips an MFA flag, a ticketing system closes a
ticket, a payments processor settles a transfer. `capsule_ledger.confirm`
turns that third-system state change into a **fulfillment capsule** —
signed, sealed, chained to the commitment it confirms — so "did this
actually happen" is answerable from the ledger, not from re-asking the
third system every time.

This page is the connector-interface reference: what a connector is, what
it must report, how the reference mock implementation works, and what a
real integration (Okta, Entra, a payments webhook) needs to implement.
Everything downstream of `ConfirmConnector.read_confirmation` — the capsule
shape, the chaining, the CLI — never changes when a mock connector is
swapped for a real one.

## The shape

```
third system state  ──(read)──▶  ConfirmConnector.read_confirmation()
                                          │
                                          ▼
                              ConfirmObservation | None
                                          │
                                          ▼
                              ConfirmIngestEngine.ingest()
                                          │
                                          ▼
                        fulfillment capsule, chained to the commitment
                        capsule it observes, appended to the ledger
```

- **No observation yet** (`read_confirmation` returns `None`): nothing is
  recorded. `ingest()` reports `pending`. Call again later — this is a
  poll-until-confirmed loop, not a one-shot decision.
- **The third system settled it** (`ConfirmObservation` returned):
  `ingest()` seals and appends exactly one fulfillment capsule. Re-ingesting
  the same event (same `external_ref`) against the same commitment never
  appends a second capsule — idempotent by construction
  (`ConfirmIngestEngine._existing`).

## Chain relation (under revision)

The current code chains the fulfillment capsule with `chain.relation="confirms"`
(`capsule_ledger/confirm/capsule.py`). That value was registered
(agent-action-capsule `REGISTRY.md` #6) for same-stream links — "attempted →
confirmed" within one agent's own action stream. A third system's state
change (an IdP, a ticketing system, a payments processor) is by definition a
*different* stream, and reusing `"confirms"` for a cross-stream observation
is a structural misuse a pending spec revision is expected to correct. Don't
take `"confirms"` here as a settled public contract: the capsule shape, the
chaining guarantee, and the CLI on this page are stable; the literal relation
value is not, pending that revision.

## `ConfirmConnector` — the interface a real integration implements

```python
from capsule_ledger.confirm import ConfirmConnector, ConfirmObservation

class MyOktaConnector:
    connector_type = "okta"

    def read_confirmation(self, *, subject: str, predicate: str) -> ConfirmObservation | None:
        ...  # call Okta's API/webhook cache; return None if nothing new
```

`ConfirmConnector` (`capsule_ledger/confirm/connector.py`) is a `Protocol`
with one method and one attribute — the same thin-seam shape as
`guards.signing.Signer`:

- `connector_type: str` — becomes `asg_payload.connector_type` on every
  capsule this connector's reads produce. "Which system confirmed this" is
  checkable directly off the capsule, never a separate lookup.
- `read_confirmation(*, subject: str, predicate: str) -> ConfirmObservation | None`
  — reads the third system's current state for one `(subject, predicate)`
  pair (e.g. `subject="user-42", predicate="mfa_enabled"`,
  `subject="ticket-9001", predicate="resolved"`,
  `subject="transfer-778", predicate="settled"`). Returns `None` when there
  is nothing new to report.

`ConfirmObservation` is what a settled read looks like:

| Field | Meaning |
|---|---|
| `status` | `"confirmed"` (it happened) or `"failed"` (the third system explicitly says it did not/will not) — the Effect Record's own reserved vocabulary. |
| `external_ref` | The third system's own reference for this event (an audit-log entry id, a webhook delivery id). Drives idempotency. |
| `observed_at` | ISO-8601 timestamp the third system reports for the event. |
| `evidence` | The connector's raw structured read. Never stored verbatim — committed into the capsule as `effect.response_digest` only. |

A real connector wraps whatever transport the third system offers
(REST polling, a webhook receiver backed by a small durable queue, an
audit-log tail) behind this one method. Nothing about polling cadence,
retries, or delivery guarantees is this interface's concern — those live in
the connector's own implementation.

## Effect-attestation grading — read this before wiring a real connector

Every fulfillment capsule carries `effect.effect_attestation`. A connector
read is graded **`runtime_claimed`** (`capsule_ledger.confirm.EFFECT_ATTESTATION_CONNECTOR_READ`),
never stronger, by construction (`build_confirm_capsule`) — the engine is
recording the *third system's own claim* about its state, not something it
observed directly at its own effect boundary. This holds for every
connector, mock or real, no matter how authoritative the third system is:
Okta's own API telling you "MFA is enabled" is still a claim being relayed,
not a receipt this codebase's own gate produced.

A stronger grade — a **counterparty-signed** confirmation the third system
itself cryptographically attests to, rather than a plain API read this
codebase has to trust — is a further-out, explicitly **not-yet-built**
rung above the mock/real-connector reference here (unrelated to, and not to
be confused with, the [outcome compiler](outcome-compiler.md)'s own
DETERMINISTIC/MANUAL/MODEL-ASSISTED verdict grades). If you are tempted to
hand-wave a real connector's read up to a stronger grade because "Okta is
trustworthy," don't — the grade describes what the *capsule* proves
independently of vendor trust, and a plain API read proves only that the
connector claims this, not that anyone can verify it without trusting the
connector.

## The reference implementation: `MockIdPConnector`

`capsule_ledger.confirm.connectors.MockIdPConnector` is a deterministic,
in-memory stand-in for an IdP, for demos and test fixtures. State is seeded
explicitly (`set_state`) — no wall-clock, no random material — so a fixed
seed produces byte-identical capsules, the same discipline
`examples/two_agents.py` uses for its own deterministic simulation.

```python
from capsule_ledger.confirm import ConfirmIngestEngine
from capsule_ledger.confirm.connectors import MockIdPConnector
from capsule_ledger.guards.signing import LocalSigner
from capsule_ledger.ledger import LedgerStore

connector = MockIdPConnector()
connector.set_state(
    subject="user-42", predicate="mfa_enabled",
    status="confirmed", external_ref="idp-evt-001", observed_at="2026-08-12T00:00:00Z",
)

signer = LocalSigner(key_id="k1", secret=b"s1")
engine = ConfirmIngestEngine(ledger=store, connector=connector, signer_provider=lambda: signer)
decision = engine.ingest(commitment_capsule_id, subject="user-42", predicate="mfa_enabled")
# decision.status == ConfirmStatus.RECORDED, decision.effect_status == "confirmed"
```

### From the CLI

```
capsule confirm ingest \
  --ledger ./my-ledger \
  --commitment <commitment-capsule-id> \
  --subject user-42 --predicate mfa_enabled \
  --status confirmed --external-ref idp-evt-001 --observed-at 2026-08-12T00:00:00Z
```

Omit `--status` to model "the third system hasn't settled this yet" — the
command prints `pending: ...` and appends nothing. `--connector` defaults
to (and currently only accepts) `mock-idp`; a real connector is wired
programmatically (below), not through this demo CLI flag.

## Wiring a real connector (Okta, Entra, a payments processor)

This is wiring, not design — the pattern above already fully specifies the
contract:

1. Implement `ConfirmConnector` against the vendor's SDK/webhook/polling
   transport. Map the vendor's own event/audit-log shape into
   `ConfirmObservation` — `status` collapses to `"confirmed"`/`"failed"`,
   everything else the vendor returns goes into `evidence` (raw, digested
   only — never re-emitted in the clear).
2. Choose a stable `external_ref` — the vendor's own delivery/event id, not
   a value you generate — so re-delivery (a webhook retry, a re-poll) is
   naturally idempotent through `ConfirmIngestEngine`'s existing-record
   check.
3. Construct `ConfirmIngestEngine` with your connector and a real
   `signer_provider`, and call `ingest()` — from a webhook handler, a
   polling loop, or a queue consumer. Nothing else in this codebase changes.
4. Do **not** grade the result above `runtime_claimed` yourself — see the
   grading section above. A stronger, independently-verifiable grade is a
   further-out, not-yet-built rung above this interface, not a connector
   change.

## What's explicitly not built here

- Any real connector (Okta, Entra, a payments processor) — this ships the
  interface and the mock reference only, per the task's own scope.
- Countersigned / `gate_executed`-or-stronger confirmation grades.
- Polling schedulers, webhook receivers, or delivery-retry infrastructure —
  connector-internal concerns, out of scope for this interface.
