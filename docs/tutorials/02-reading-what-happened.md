# Reading what happened

**Goal:** you weren't watching last night. Your agent (or two) made 7
decisions against the **ledger** — an append-only, signed trail of actions
and guard verdicts, no blockchain involved. Answer "what did it do, and was
any of it weird?" using nothing but the investigation verbs, against the
same fixture from tutorial 1 (`/tmp/demo-ledger.jsonl` — regenerate it with
`python -m capsule_ledger.examples.two_agents --out /tmp/demo-ledger.jsonl`
if you don't have it).

## Narrow the log: filters

`capsule log` takes the same filters everywhere in this repo:
`--agent`, `--since`/`--until`, `--counterparty`, `--verdict`,
`--action-type`, `--limit`.

Show only the records a guard actually blocked:

```console
$ capsule log --ledger /tmp/demo-ledger.jsonl --verdict blocked
```

```
≡ capsule log --verdict blocked

capsule 3f469ffa09b1f0e3842c4765e089dd96a8aabd996dea7f5e1547a51ca9d8c5c8
Agent:    checkout-agent-alpha@v1
...
capsule d5d804d676705c9a9ea6d8aab2ac7be93ee8c191c99d83dd2ef92d8cabd4ac2f
Agent:    checkout-agent-beta@v1
...
2 of 7 records shown (filtered view — the ledger itself is never filtered) · sequence unbroken · as of just now
```

Notice the footer: `2 of 7 records shown ... the ledger itself is never
filtered`. `log` narrows what you're *looking at*, never what's stored.

## One record in full: `capsule show`

Already covered in tutorial 1 — worth repeating here because it's your
main tool for "what exactly happened in this one case": agent, operator,
verdict, and each constraint the guard ran, by name and result.

## Compare two points in time: `capsule diff`

`diff` takes two checkpoint refs — a sequence number, a capsule id, an
ISO timestamp, or `HEAD` — and shows what changed between them:

```console
$ capsule diff 0 6 --ledger /tmp/demo-ledger.jsonl
```

```
capsule diff: checkpoint #0 (0) → checkpoint #6 (6)

6 new record(s):
  + capsule f0fb5d6724d21acb  (none)      checkout-shared-treasury@v1  transfer_funds
  + capsule 57b296e8ab4eb743  hitl_dispatched  checkout-shared-treasury@v1  transfer_funds
  + capsule 25af0ca6c727239e  (none)      checkout-agent-alpha@v1   send_compliance_report
  + capsule 3f469ffa09b1f0e3  blocked     checkout-agent-alpha@v1   send_compliance_report
  + capsule d5d804d676705c9a  blocked     checkout-agent-beta@v1    delete_customer_record
  + capsule ee291fae9e673d1b  confirmed   checkout-agent-alpha@v1   intent.declare

verdict distribution delta:
  (none): 0 → 2 (+2)
  blocked: 0 → 2 (+2)
  confirmed: 0 → 1 (+1)
  hitl_dispatched: 0 → 1 (+1)

as of just now

≡ capsule diff 0 6
```

Pass `--fold <fold_id> --key <group>` to also see a fold's cumulative
result move between the two checkpoints — useful for "how much did this
agent's counter move overnight":

```console
$ capsule diff 0 6 --ledger /tmp/demo-ledger.jsonl \
    --fold actions.count_by_developer/1.0.0 --key checkout-agent-alpha@v1
```

```
fold deltas:
  actions.count_by_developer/1.0.0: 0 → 3
```

(One honest wrinkle: some folds, like `spend.weekly/1.0.0`, are rolling-window
folds that require an explicit `--as-of` timestamp somewhere downstream of
the record data — `diff --fold` doesn't expose that flag, so a
rolling-window fold isn't diffable this way today. Use `capsule fold test`
for those, covered in tutorial 3.)

## Trace a decision back: `capsule blame`

The dedupe-collision record above (`3f469ffa…`) didn't come from nowhere —
it's chained back to the original action it duplicated. `blame` walks that
chain:

```console
$ capsule blame 3f469ffa --ledger /tmp/demo-ledger.jsonl
```

```
capsule 3f469ffa09b1f0e3842c4765e089dd96a8aabd996dea7f5e1547a51ca9d8c5c8  (target)
  seq:      #4
  Agent:    checkout-agent-alpha@v1
  Verdict:  blocked
  Date:     2026-08-07T09:00:51Z
  Action:   send_compliance_report
  ↑ chain.relation='confirms'

capsule 25af0ca6c727239efe8bbf1b7e081b32b61787e6d424e4cd8c972ec1e5f86ab8
  seq:      #3
  Agent:    checkout-agent-alpha@v1
  Verdict:  (none)
  Date:     2026-08-07T09:00:34Z
  Action:   send_compliance_report

2 hop(s) in chain · root reached — this record carries no chain (standalone)

≡ capsule blame 3f469ffa
```

`blame` follows `chain.parent_capsule_id` links only — it's a chain walk,
not a semantic "why," but for the mechanical question ("what record led to
this one, and what led to that") it's exact.

## Find the first record where something became true: `capsule bisect`

"When did my agent's first `blocked` verdict happen?" — instead of eyeballing
the log, ask directly:

```console
$ capsule bisect --verdict blocked --ledger /tmp/demo-ledger.jsonl
```

```
first record where disposition.verdict_class == 'blocked':

capsule 3f469ffa09b1f0e3842c4765e089dd96a8aabd996dea7f5e1547a51ca9d8c5c8
  seq:      #4 (of 7)
  Agent:    checkout-agent-alpha@v1
  Verdict:  blocked
  Date:     2026-08-07T09:00:51Z
  Action:   send_compliance_report

≡ capsule bisect --verdict blocked
```

`bisect` also takes `--fold <fold_ref> --gt/--gte/--lt/--lte <threshold>`
instead of `--verdict`, to find the first record where a fold's cumulative
value crosses a line (e.g. the first record where a running spend total
passed some number) — that path needs the fold's window resolved, same
caveat as `diff --fold` above.

## You just

Went from a raw ledger to concrete answers — what got blocked, what
changed between two points, what led to a given record, and when the first
bad verdict landed — without writing a line of code.

**Next:** [Folds and caps →](03-folds-and-caps.md)
