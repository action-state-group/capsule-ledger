# Folds and caps

**Goal:** understand the two moving parts behind that `hitl_dispatched`
verdict in your ledger — the guard's registered checks, and the fold that
one of them (`caps`) evaluates against — plus the manifest that pins which
version of both was in force when a decision was made.

Still using `/tmp/demo-ledger.jsonl` from tutorial 1.

## The guard checks and the action-class taxonomy: `capsule constraints`

```console
$ capsule constraints list
```

```
checks:
  dedupe                   policy   exact_match_index_v0         equivalence lookup over a rolling window — exact-match only, no fuzzy/semantic matching
  caps                     policy   spend.weekly/1.0.0           fold predicate: weekly_spend + amount <= cap (integer minor units only)
  verify_before_dispatch   policy   agent_action_capsule.verify  the cited mandate capsule must exist in the ledger and independently re-verify

action classes (absent or unrecognized -> unclassified, fail-closed):
  money.transfer       consequential=True   fail_open_allowed=False
  data.delete          consequential=True   fail_open_allowed=False
  comms.external       consequential=True   fail_open_allowed=False
  info.query           consequential=False  fail_open_allowed=True
  unclassified         consequential=True   fail_open_allowed=False
```

Three checks, always. `caps` is the one that decides spend; `dedupe` caught
the collision in tutorial 2; `verify_before_dispatch` is the one the
refusal record (`d5d804d6…`) hard-failed on — a cited mandate capsule that
was never recorded.

## The fold catalog: `capsule fold list`

A **fold** is a pure, replayable aggregation over the ledger — the thing
`caps` actually evaluates against.

```console
$ capsule fold list
```

```
actions.count_by_developer/1.0.0	9574753ce2967f281067e0a12d9ae279763ccfe50040e1156eba444f97a21bc6	/tmp/cl/capsule_ledger/folds/catalog_defs/actions.count_by_developer.yaml
actions.executed_count/1.0.0	9b2abc127ecaee1f9b46c36c03217019f8f8903a1514dc9ebe41d3c2e954d463	/tmp/cl/capsule_ledger/folds/catalog_defs/actions.executed_count.yaml
actions.last_decision/1.0.0	875cd831a00edee5c3a117cc5bc7e2820c158b3c018598f2ac8fb59820b8a191	/tmp/cl/capsule_ledger/folds/catalog_defs/actions.last_decision.yaml
spend.weekly/1.0.0	3e7f6a3e8707de92b120bbc2aa0b5a78032df5d36e99f9955dd3ba948bba5e9c	/tmp/cl/capsule_ledger/folds/catalog_defs/spend.weekly.yaml
```

The middle column is the fold **definition's digest** — every fold in the
catalog is content-addressed, not just named. That digest is what a
decision capsule ultimately pins (via the manifest, below), so "which rule
version applied" is never a guess.

## The caps check story, with envelopes

`money.transfer` has a shared weekly cap of **10,000.00 EUR**, pooled
across both agents (they draw against the same `checkout-shared-treasury@v1`
identity). Alpha goes first, well under the cap:

```console
$ capsule show f0fb5d67 --ledger /tmp/demo-ledger.jsonl --json
```

```json
{
  "asg_payload": { "action_class": "money.transfer", "amount_minor": 650000, "currency": "EUR", ... },
  "constraints": [
    { "id": "dedupe", "result": "pass", "method": "exact_match_index_v0", "severity": "blocking" },
    { "id": "caps",   "result": "pass", "method": "spend.weekly/1.0.0",   "severity": "blocking" },
    { "id": "verify_before_dispatch", "result": "n/a", "severity": "blocking" }
  ],
  "disposition": { "decision": "accept", "verdict_class": null }
}
```

Alpha's transfer is 6,500.00 EUR (`amount_minor: 650000`) — `caps` passes.
Right after, Beta draws 6,000.00 EUR against the same pooled identity:

```console
$ capsule show 57b296e8 --ledger /tmp/demo-ledger.jsonl --json
```

```json
{
  "asg_payload": { "action_class": "money.transfer", "amount_minor": 600000, "currency": "EUR", ... },
  "constraints": [
    { "id": "dedupe", "result": "pass", "method": "exact_match_index_v0", "severity": "blocking" },
    { "id": "caps",   "result": "fail", "method": "spend.weekly/1.0.0",   "severity": "blocking" },
    { "id": "verify_before_dispatch", "result": "n/a", "severity": "blocking" }
  ],
  "disposition": { "decision": "hitl_dispatched", "verdict_class": "hitl_dispatched", "approver": "policy" }
}
```

Pooled: 6,500 + 6,000 = 12,500 EUR against a 10,000 EUR cap. `caps` fails
— but the verdict is **`hitl_dispatched`**, not a hard deny. That's
because `money.transfer` has an `approver_role` configured in the action
class taxonomy: a cap-exceeded action in a class with an approver escalates
to a human decision rather than hard-denying outright. (`data.delete` and
`comms.external`, which have no approver role, do hard-deny on a failed
check — that's what happened to the refusal record in tutorial 1.)

**Never read a bare number off a fold.** Ask for a fold's own envelope with
`capsule fold test`, which always returns the fold's result *with* its
provenance — never just the number:

```console
$ capsule fold test spend.weekly/1.0.0 --ledger /tmp/demo-ledger.jsonl \
    --key checkout-shared-treasury@v1 --as-of 2026-08-07T09:01:42Z
```

```json
{
  "checkpoint": { "tree_size": 7 },
  "evaluated_at": "2026-08-07T21:59:03.077540+00:00",
  "fold": "3e7f6a3e8707de92b120bbc2aa0b5a78032df5d36e99f9955dd3ba948bba5e9c",
  "range": [0, 6],
  "result": 650000,
  "staleness": { "checkpoint_age_ms": 0 },
  "tree_size": 7
}
```

Honest wrinkle: `spend.weekly` is a rolling-window fold, so it requires an
explicit `--as-of` — the engine never consults a wall clock to supply one
(a record-derived reference, not "now," so the same replay always produces
the same window). Also worth noting: the pooled total this fold reports
(650000, i.e. 6,500 EUR) reflects only the *accepted* transfer, not the
escalated one — read `result` alongside `range` and `checkpoint`, never on
its own, exactly because the number changes meaning depending on which
records are in scope.

## Validate a fold definition before trusting it: `capsule fold lint`

```console
$ capsule fold lint /tmp/cl/capsule_ledger/folds/catalog_defs/spend.weekly.yaml
```

```
ok  spend.weekly/1.0.0  3e7f6a3e8707de92b120bbc2aa0b5a78032df5d36e99f9955dd3ba948bba5e9c
```

`lint` is a static check on the YAML definition itself (well-formed,
resolvable digest) — it doesn't replay it against any ledger; `fold test`
is what actually runs it.

## Declare–attest–verify: `capsule manifest show`

A **manifest** is the pinned bundle of fold + guard-check definitions a
deployment declares itself bound to — declare it, attest it (activate),
and any later decision can be verified against exactly that pinned set.

```console
$ capsule manifest show
```

```
manifest default/1.0.0  0e99f3ee3a6ebf3ee93aa464f27e8fcd1a401ccc45460eb267efde327f5c218c
  source: /tmp/cl/capsule_ledger/policy/catalog_defs/default.yaml
  fold    spend.weekly/1.0.0       3e7f6a3e8707de92b120bbc2aa0b5a78032df5d36e99f9955dd3ba948bba5e9c  OK
  wicket  dedupe/1.0.0             18ab5d489f1e5774d576b8f99897edd4f4b20f609b85683456a3e3b6b4912abb  OK
  wicket  caps/1.0.0               906a75a0b908d38fa7b05823ba11f229c3d593516119ad757b541cee7083f54b  OK
  wicket  verify_before_dispatch/1.0.0 a721624813f785de49f3dcef2090662e7045bc393e59db72defcdbf47269453c  OK
```

Every fold and check the manifest declares is **digest-listed** — `OK`
means that digest actually resolves against the real catalog on disk, not
just that a name matched. `manifest activate` appends a signed
config-change record citing this manifest's own digest (`0e99f3ee…`), and
`manifest verify` confirms a given decision capsule's cited manifest digest
still resolves to a real, loadable manifest — so "which policy was live
when this decision was made" is answerable from the ledger itself, not
from a separate change log you have to trust.

## You just

Read a real caps escalation end to end — two agents, one pooled identity,
one shared cap, an `approver_role` turning a failed check into
`hitl_dispatched` instead of a hard deny — and saw the fold and manifest
machinery underneath every verdict, always with its envelope, never a bare
number.

**Next:** [Bundle and verify →](04-bundle-and-verify.md)
