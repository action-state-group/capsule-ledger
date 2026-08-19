# capsule-ledger

capsule-ledger is a local control plane for AI agent actions: an append-only ledger, verifiable folds over it, and guards that check actions against them before they dispatch.

It gives you limits your agents cannot exceed, memory they cannot lie about.

Every guard decision, every fold result, and every refusal is a record — checkable by replay, not by trusting the process that produced it. The ledger runs where your agents run; nothing leaves your environment to be checked.

**This is not a limited edition of something else.** capsule-ledger is the complete
local control plane, full stop — not a trial, not a stripped-down preview of a
hosted product. See [`docs/oss-project-scope.md`](docs/oss-project-scope.md) for
the exact boundary of what belongs in this repository and why.

## Quickstart (5 minutes)

The fastest way to a real, verifiable ledger — no hand-typed capsules, no mocks:

```console
$ pip install -e ".[dev]"
$ python -m capsule_ledger.examples.two_agents --out /tmp/demo-ledger.jsonl
two-agents demo sim: 7 capsule(s) recorded, seed=20260807, backend=local
  overlap_spend_alpha          allow      f0fb5d6724d21acb…
  overlap_spend_beta_escalated escalate   57b296e8ab4eb743…
  dedupe_original              allow      25af0ca6c727239e…
  dedupe_collision             deny       3f469ffa09b1f0e3…
  refusal                      deny       d5d804d676705c9a…
  intent_declare               declared   ee291fae9e673d1b…
  intent_fulfill               allow      595847ca81caff1b…
fixture written to /tmp/demo-ledger.jsonl

$ capsule log --ledger /tmp/demo-ledger.jsonl      # read it back
$ capsule verify f0fb5d67 --ledger /tmp/demo-ledger.jsonl
✓ verifies · f0fb5d6724d21acb33a3b7fe2c1b80e222ca2e1a86086631126581f606183e9b
```

That's a real, signed, append-only `.jsonl` file on disk, read back by a
different command than the one that wrote it — a write path that only checks
itself isn't verification. Full walkthrough, with every command's exact
output: [`docs/tutorials/01-your-first-ledger.md`](docs/tutorials/01-your-first-ledger.md).

## Onboarding your own agent

Four ways to hook a real agent up to a capsule-ledger instance (Claude Code,
Goose, a framework adapter, Dapr), each ending in a real, independently
verifiable record — see [`docs/onboarding.md`](docs/onboarding.md). **Two of
the four paths aren't built yet; the doc says so plainly rather than
inventing them** — Goose and Dapr have no integration code in this repo yet.

## What's here

- `capsule_ledger/ledger/` — append-only store and the query API (agent, time range, counterparty, verdict, action type).
- `capsule_ledger/folds/` — declarative fold definitions (count/sum/min/max/last, keyed and windowed) and their replay evaluation.
- `capsule_ledger/guards/` — the guard API: `check(action) -> allow | deny | escalate`, plus `dry_run`.
- `capsule_ledger/report/` — `capsule guard dry-run`: replays a ledger through the guard checks and emits a
  self-contained HTML report. The report's cited records travel only in the shared link's URL
  fragment (after `#`), never server-side or fetched — the page re-derives its own numbers and
  re-verifies every cited capsule's digest from that fragment when opened.
- `capsule_ledger/cli/` — the `capsule` command line (git-verb shaped: `log`, `show`, `verify`, `bundle`, `fold`, ...).
- `capsule_ledger/mcp/` — an MCP advisory server exposing the same ledger, folds, and guards to agent harnesses (nine read-only tools, plus `intent_declare` — the only tool that writes).
- `capsule_ledger/vectors/` — pinned test vectors: known-answer results, determinism probes, and MUST-FAIL cases.
- `capsule_ledger/telemetry/` — opt-in-disclosed, aggregate-only usage instrumentation and the 6-metric funnel report generator (see below).

## Packaging

Select runtime with `$CAPSULE_LEDGER_ARM`

- `full` (default) — everything: the guard checks plus the evidence surfaces (`log`/`show`/`verify`/`bundle`, permalinks, the dry-run report's share/verify chrome).
- `guards-only` (`CAPSULE_LEDGER_ARM=guards-only`) — a minimal profile registering only the guard commands.

See `capsule_ledger/packaging.py` for the mechanism and the reasoning behind picking an env var over a pip extra, a config file, or a per-command flag.

## Telemetry

Off by default. If explicitly turned on (`CAPSULE_LEDGER_TELEMETRY=1`), this install reports a handful of yes/no or count-shaped facts about how the package gets used (e.g. "was a guard configured shortly after install") — never what was configured, blocked, or held, and never any ledger content. Run `capsule telemetry status` to see the full disclosure text and current state, and `capsule telemetry funnel --dry-run` to see the report shape rendered against synthetic data. See `capsule_ledger/telemetry/` for the implementation.

## Failure semantics

The guard fails closed by default and records every degradation — see
[`docs/failure-semantics.md`](docs/failure-semantics.md) for the full table.

## CI Action for downstream repos

`.github/actions/guard-check` is a composite GitHub Action other repos can
`uses:` in their own CI to lint a guard config, replay it against a
snapshot ledger, and epoch-diff guard behavior on PRs — see
[`docs/ci-action.md`](docs/ci-action.md), including the honesty line on
what pre-merge CI does and does not guarantee versus the live guard.

## Capsule parsing

Records are parsed and verified through the public [`agent-action-capsule`](https://github.com/action-state-group/agent-action-capsule) reference library (published as `agent-action-capsule` on PyPI), declared as a normal dependency. It is never vendored or copied into this repo.

## Install

```bash
pip install -e ".[dev]"
```

## Develop

```bash
ruff check .
pytest -q
```

## Status

315 files, 700+ passing tests, a working guard engine, and adversarial review.
Community supported open source.
