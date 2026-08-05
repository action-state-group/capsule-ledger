# asg-ledger

asg-ledger is a local control plane for AI agent actions: an append-only ledger, verifiable folds over it, and guards that check actions against them before they dispatch.

It gives you limits your agents cannot exceed, memory they cannot lie about.

Every guard decision, every fold result, and every refusal is a record — checkable by replay, not by trusting the process that produced it. The ledger runs where your agents run; nothing leaves your environment to be checked.

## What's here

- `asg_ledger/ledger/` — append-only store and the query API (agent, time range, counterparty, verdict, action type).
- `asg_ledger/folds/` — declarative fold definitions (count/sum/min/max/last, keyed and windowed) and their replay evaluation.
- `asg_ledger/guards/` — the guard API: `check(action) -> allow | deny | escalate`, plus `dry_run`.
- `asg_ledger/cli/` — the `asg` command line (git-verb shaped: `log`, `show`, `verify`, `bundle`, `fold`, ...).
- `asg_ledger/mcp/` — a read-only MCP advisory server exposing the same ledger, folds, and guards to agent harnesses.
- `asg_ledger/vectors/` — pinned test vectors: known-answer results, determinism probes, and MUST-FAIL cases.

This is a scaffold. The subpackages above are stubs; behavior lands incrementally.

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
