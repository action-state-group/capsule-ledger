# capsule-ledger

capsule-ledger is a local control plane for AI agent actions: an append-only ledger, verifiable folds over it, and guards that check actions against them before they dispatch.

It gives you limits your agents cannot exceed, memory they cannot lie about.

Every guard decision, every fold result, and every refusal is a record — checkable by replay, not by trusting the process that produced it. The ledger runs where your agents run; nothing leaves your environment to be checked.

## What's here

- `asg_ledger/ledger/` — append-only store and the query API (agent, time range, counterparty, verdict, action type).
- `asg_ledger/folds/` — declarative fold definitions (count/sum/min/max/last, keyed and windowed) and their replay evaluation.
- `asg_ledger/guards/` — the guard API: `check(action) -> allow | deny | escalate`, plus `dry_run`.
- `asg_ledger/report/` — `capsule guard dry-run`: replays a ledger through the guard checks and emits a
  self-contained HTML report. The report's cited records travel only in the shared link's URL
  fragment (after `#`), never server-side or fetched — the page re-derives its own numbers and
  re-verifies every cited capsule's digest from that fragment when opened.
- `asg_ledger/cli/` — the `capsule` command line (git-verb shaped: `log`, `show`, `verify`, `bundle`, `fold`, ...).
- `asg_ledger/mcp/` — an MCP advisory server exposing the same ledger, folds, and guards to agent harnesses (nine read-only tools, plus `intent_declare` — the only tool that writes).
- `asg_ledger/vectors/` — pinned test vectors: known-answer results, determinism probes, and MUST-FAIL cases.
- `asg_ledger/telemetry/` — opt-in-disclosed, aggregate-only usage instrumentation and the 6-metric funnel report generator (see below).

This is a scaffold. The subpackages above are stubs; behavior lands incrementally.

## Two packaging arms

One codebase, one wheel, two arms — selected at runtime with `$ASG_LEDGER_ARM`, never a separate build:

- `full` (default) — everything: the guard checks plus the evidence surfaces (`log`/`show`/`verify`/`bundle`, permalinks, the dry-run report's share/verify chrome).
- `guards-only` (`ASG_LEDGER_ARM=guards-only`) — the same guard checks (caps/dedupe/verify-before-dispatch + `dry_run`), but the evidence machinery underneath stays silent: no capsule vocabulary in CLI output, no permalinks or verify-link suggestions, and the evidence-surfacing commands (`log`/`show`/`verify`/`bundle`) aren't even registered.

See `asg_ledger/packaging.py` for the mechanism and the reasoning behind picking an env var over a pip extra, a config file, or a per-command flag.

## Telemetry

Off by default. If explicitly turned on (`ASG_LEDGER_TELEMETRY=1`), this install reports a handful of yes/no or count-shaped facts about how the package gets used (e.g. "was a guard configured shortly after install") — never what was configured, blocked, or held, and never any ledger content. Run `capsule telemetry status` to see the full disclosure text and current state, and `capsule telemetry funnel --dry-run` to see the report shape rendered against synthetic data. See `asg_ledger/telemetry/` for the implementation.

## Failure semantics

The guard fails closed by default and records every degradation — see
[`docs/failure-semantics.md`](docs/failure-semantics.md) for the full table.

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

Early scaffold. No stability guarantees yet.
