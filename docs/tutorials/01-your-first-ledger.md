# Your first ledger

**Goal:** generate a real ledger, look at what's in it, and verify it — the
full day-1 loop. ~5 minutes.

## 1. Install

```console
$ pip install -e ".[dev]"
```

This installs the `capsule` console script plus everything the examples
below need (pytest, ruff, the MCP server, and `capsule-emit` for the
simulator).

## 2. Generate a real ledger

capsule-ledger's **ledger** is an append-only, signed record of actions an
agent took and what the guard decided about each one — no blockchain, no
tokens, no consensus involved. Rather than hand-typing capsules, the
fastest way to get a real one is the repo's own deterministic simulator: it
plays two scripted agents ("checkout-agent-alpha@v1" and
"checkout-agent-beta@v1") against one shared ledger, hitting a shared
spending cap, a dedupe collision, a refusal, and a declared-intent chain
along the way.

```console
$ python -m capsule_ledger.examples.two_agents --out /tmp/demo-ledger.jsonl
```

```
two-agents demo sim: 7 capsule(s) recorded, seed=20260807, backend=local
  overlap_spend_alpha          allow      f0fb5d6724d21acb…
  overlap_spend_beta_escalated escalate   57b296e8ab4eb743…
  dedupe_original              allow      25af0ca6c727239e…
  dedupe_collision             deny       3f469ffa09b1f0e3…
  refusal                      deny       d5d804d676705c9a…
  intent_declare               declared   ee291fae9e673d1b…
  intent_fulfill               allow      595847ca81caff1b…
fixture written to /tmp/demo-ledger.jsonl
```

That's a real `.jsonl` file on disk now — one capsule per line, 7 lines.
Every command in this tutorial (and the next three) runs against this
exact file, so you can follow along with your own copy and see the same
ids.

## 3. Look at it: `capsule log`

```console
$ capsule log --ledger /tmp/demo-ledger.jsonl
```

```
≡ capsule log

capsule f0fb5d6724d21acb33a3b7fe2c1b80e222ca2e1a86086631126581f606183e9b
Agent:    checkout-shared-treasury@v1
Operator: acme-checkout
Verdict:  (none)
Date:     2026-08-07T09:00:00Z

    transfer_funds

capsule 57b296e8ab4eb7430445c28c34b72dd97d2fc214e8c44df23cb2052803773c38
Agent:    checkout-shared-treasury@v1
Operator: acme-checkout
Verdict:  hitl_dispatched
Date:     2026-08-07T09:00:17Z

    transfer_funds
  ...
7 of 7 records shown (filtered view — the ledger itself is never filtered) · sequence unbroken · as of just now
```

(Output above is trimmed to the first two records — your terminal will show
all 7.) `--ledger` points at a JSONL fixture file here; if you were running
a live agent across many process invocations you'd point it at a directory
instead and set `$CAPSULE_LEDGER` (see `docs/onboarding.md`) — a fixture
file gets re-imported into a throwaway store on every CLI call, which is
fine for reading but not for accumulating writes across processes.

## 4. Look inside one record: `capsule show`

Pick any id (or an unambiguous prefix of one) from the log above:

```console
$ capsule show f0fb5d67 --ledger /tmp/demo-ledger.jsonl
```

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

≡ capsule show f0fb5d6724d21acb33a3b7fe2c1b80e222ca2e1a86086631126581f606183e9b
```

`--json` on `show` gets you the raw capsule for scripting; `--json` also
works on `log`.

## 5. Prove it's real: `capsule verify`

Verify one record by id (an ambiguous-free prefix works):

```console
$ capsule verify f0fb5d67 --ledger /tmp/demo-ledger.jsonl
```

```
✓ verifies · f0fb5d6724d21acb33a3b7fe2c1b80e222ca2e1a86086631126581f606183e9b

≡ capsule verify f0fb5d6724d21acb33a3b7fe2c1b80e222ca2e1a86086631126581f606183e9b
```

There's no whole-ledger "verify everything at once" flag on `capsule
verify` today — you verify a record by id, or verify a whole slice at once
via `capsule bundle` (tutorial 4). Edit one byte of `/tmp/demo-ledger.jsonl`
and re-run the command above — verification fails. That mismatch is what
makes the record trustworthy to someone who didn't write it, not you
promising it's fine.

## Why the run was byte-identical every time

Run the simulator again, to a new file:

```console
$ python -m capsule_ledger.examples.two_agents --out /tmp/demo-ledger-2.jsonl
$ diff /tmp/demo-ledger.jsonl /tmp/demo-ledger-2.jsonl && echo IDENTICAL
```

```
IDENTICAL
```

That's not a coincidence — it's the point of the simulator. Every source of
non-determinism the underlying capsule-signing path could introduce (the
two agents' signing keys, the intent capsule's synthetic id, and even the
wall-clock/`uuid4()` calls buried inside `capsule-emit`'s own `emit()`) is
derived from a single `--seed` (default `20260807`, fixed in the code, not
today's date). Same seed in, byte-identical ledger out; a different
`--seed` produces a genuinely different one. That's also why this tutorial
can show you exact ids and exact bytes and expect your terminal to match —
determinism, here, is the product, not an incidental nicety.

**Next:** [Reading what happened →](02-reading-what-happened.md)
