# Concepts in plain words

Nine words cover everything. Each one is a real field you can see in a capsule, or a real
`capsule` command run against `tests/fixtures/two_agents_sim_ledger.jsonl` — no theory
required.

### Capsule
One decision, sealed as a single JSON record. `capsule show <id>` prints it:

```
capsule f0fb5d6724d21acb33a3b7fe2c1b80e222ca2e1a86086631126581f606183e9b
Agent:      checkout-shared-treasury@v1
Operator:   acme-checkout
Action:     transfer_funds (decide)
Date:       2026-08-07T09:00:00Z
Verdict:    (none)
Assurance:  self_attested · standalone
Chain:      (none)
Constraints:
  - dedupe: pass
  - caps: pass
  - verify_before_dispatch: n/a
```

The real fields backing that view are `capsule_id`, `action_id`, `action_type`,
`developer`, `operator`, `timestamp`, `disposition`, and `constraints`. It's plain JSON,
one line per record in the ledger file.

### Ledger
Your local, append-only file of capsules — the running trail of everything the guard has
decided. **An append-only signed log of records — no blockchain, no tokens, no
consensus.** It's a `.jsonl` file (or a store directory); read it with:

```
capsule log --ledger tests/fixtures/two_agents_sim_ledger.jsonl
```

which prints one entry per capsule, oldest first — git-log style. `capsule show <id>`
gives you one record in full — git-show style.

### Guard
The thing that runs before an action is allowed to happen. `GuardEngine` (in
`capsule_ledger/guards/engine.py`) runs the registered checks against an `Action`,
decides `allow` / `deny` / `escalate`, and appends the decision as a capsule — it doesn't
just log, it's in the path. `capsule constraints list` shows exactly which checks are
registered and how they classify actions:

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

Note the last row: an action with no recognized class fails closed by default, not open.
What happens when the guard itself can't reach the ledger, the view, or the signer is
its own page — see [failure semantics](failure-semantics.md).

### Verdict
What the guard decided, recorded on the capsule's `disposition`. There are three shapes
in the code (`guards/capsule.py`):

| `GuardEngine` outcome | `disposition.decision` | `disposition.verdict_class` |
|---|---|---|
| `allow` | `accept` | *(none — a clean allow has no verdict_class)* |
| `deny` | `reject` | `blocked` |
| `escalate` | `hitl_dispatched` | `hitl_dispatched` |

You can see all three in the fixture: `capsule log` shows one record with `Verdict: (none)`
(an allow), one with `Verdict: hitl_dispatched` (escalated to a human), and one with
`Verdict: blocked` (denied). `escalate` deliberately reuses `hitl_dispatched` for both
fields — the spec's word for "dispatched to a human, not yet resolved."

### Fold
A named, versioned aggregate over the ledger — a spend total, a count, a "last decision"
lookup. Folds live in a catalog; `capsule fold list` shows what's registered, each with
its own content digest:

```
actions.count_by_developer/1.0.0	9574753ce2967f281067e0a12d9ae279763ccfe50040e1156eba444f97a21bc6	.../actions.count_by_developer.yaml
actions.executed_count/1.0.0	9b2abc127ecaee1f9b46c36c03217019f8f8903a1514dc9ebe41d3c2e954d463	.../actions.executed_count.yaml
actions.last_decision/1.0.0	875cd831a00edee5c3a117cc5bc7e2820c158b3c018598f2ac8fb59820b8a191	.../actions.last_decision.yaml
spend.weekly/1.0.0	3e7f6a3e8707de92b120bbc2aa0b5a78032df5d36e99f9955dd3ba948bba5e9c	.../spend.weekly.yaml
```

`spend.weekly/1.0.0` is the same fold `caps` uses to decide whether a transfer fits under
a weekly cap — a fold isn't just a report, the guard runs one on the hot path.

### Envelope
**A fold result is never a bare number.** Every fold evaluation comes wrapped in an
envelope that says exactly what was measured, over what, and how fresh it is. Running
`capsule fold test` against the fixture:

```
capsule fold test --ledger tests/fixtures/two_agents_sim_ledger.jsonl \
  actions.executed_count/1.0.0 --as-of 2026-08-07T09:05:00Z
```
```json
{
  "checkpoint": { "tree_size": 7 },
  "evaluated_at": "2026-08-07T21:58:04.111052+00:00",
  "fold": "9b2abc127ecaee1f9b46c36c03217019f8f8903a1514dc9ebe41d3c2e954d463",
  "range": [0, 6],
  "result": 0,
  "staleness": { "checkpoint_age_ms": 0 }
}
```

The four things an envelope always carries:
- **fold definition digest** — the `fold` field above, the exact content hash of the fold
  definition that produced this number, not just its name.
- **record range** — `range`, which ledger records were actually folded.
- **checkpoint** — `checkpoint.tree_size`, which ledger state this was computed against.
- **staleness** — `staleness.checkpoint_age_ms`, how old that checkpoint was when the
  result was used.

A rolling-window fold (like `spend.weekly`) refuses to run without an explicit `--as-of`:
running it without one fails with `as_of_required_not_wall_clock` — the engine never
consults a wall clock to backfill a reference time for you, on purpose.

### Policy manifest
The declared, pinned list of which fold and wicket (guard-check) definitions are
active — by digest, not by copy. `capsule manifest show` resolves the built-in default
manifest against the real catalogs:

```
manifest default/1.0.0  0e99f3ee3a6ebf3ee93aa464f27e8fcd1a401ccc45460eb267efde327f5c218c
  source: .../policy/catalog_defs/default.yaml
  fold    spend.weekly/1.0.0       3e7f6a3e8707de92b120bbc2aa0b5a78032df5d36e99f9955dd3ba948bba5e9c  OK
  wicket  dedupe/1.0.0             18ab5d489f1e5774d576b8f99897edd4f4b20f609b85683456a3e3b6b4912abb  OK
  wicket  caps/1.0.0               906a75a0b908d38fa7b05823ba11f229c3d593516119ad757b541cee7083f54b  OK
  wicket  verify_before_dispatch/1.0.0 a721624813f785de49f3dcef2090662e7045bc393e59db72defcdbf47269453c  OK
```

Each `OK` means: the digest the manifest cites for that fold/wicket matches what's
actually sitting in the catalog right now. The manifest itself gets a digest the same
way (`manifest_digest()` in `capsule_ledger/policy/manifest.py`) — declare, attest,
verify, same pattern as the fold digests above.

### Epoch
A policy manifest doesn't get edited in place — activating a new one appends a capsule
whose `chain.relation` is `epoch_opens` (see `capsule_ledger/policy/activation.py`),
pointing back at the previous activation if there was one. That gives the ledger a
walkable history of policy epochs: which manifest digest was active, from which capsule
onward. `capsule manifest activate` is what appends that record; `capsule diff` and
`capsule blame` are how you compare state across, or trace a record back to, one of
those boundaries.

### Bundle
A self-contained, offline-verifiable slice of the ledger. `capsule bundle` writes one:

```
capsule bundle --ledger tests/fixtures/two_agents_sim_ledger.jsonl --out /tmp/bundle.json
```
```
wrote /tmp/bundle.json (7 record(s), records 1–7, all verify)
checkpoint #7 · as of just now
verify: https://verify.agentactioncapsule.org/bundle#eyJidW5kbGVfdmVyc2lvbiI6IjEi...
```

The bundle file itself carries `bundle_version`, `checkpoint`, `range`, and the raw
`records` — everything needed to re-verify without touching the live ledger. `capsule
verify --bundle /tmp/bundle.json` checks it back, offline:

```
✓ verifies · f0fb5d6724d21acb33a3b7fe2c1b80e222ca2e1a86086631126581f606183e9b
✓ verifies · 57b296e8ab4eb7430445c28c34b72dd97d2fc214e8c44df23cb2052803773c38
...
bundle /tmp/bundle.json: 7 record(s), verifies clean
```

Verification is free and unmetered — anyone with the bundle file can run `capsule
verify` themselves, no account, no server call back to this project.

---

Want to *see* these instead of read them? Do the [tutorials](tutorials/) — they're
five-minute, copy-paste sessions. Want the failure-mode detail behind "guard"?
[Failure semantics](failure-semantics.md). Want the honest state of signing?
[Key management](key-management.md).
