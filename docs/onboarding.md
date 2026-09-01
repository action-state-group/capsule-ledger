# Onboarding: hooking an agent up to capsule-ledger

Three ways to connect an agent (or an agent framework) to a capsule-ledger
instance. Every command below was run against this repo's real code before
it was written down here — none of it is illustrative pseudocode. Two of
the three paths (Goose, Dapr) don't have real integration code in this repo
yet; those sections say so plainly instead of inventing a package or a
config format that doesn't exist. See "What's real, what isn't" at the
bottom for the honest scorecard.

Each path below ends the same way: a real record lands in a real ledger,
and you confirm it with a *different* tool than the one that wrote it
(`capsule log` / `capsule verify`) — because a write path that only checks
itself isn't verification.

> **MCP server moved.** The MCP advisory server (`capsule-mcp`, nine read
> tools + `intent_declare`) that used to live at `capsule_ledger/mcp/` now
> ships from `capsule-engine`, alongside this ledger's other operational
> (non-honest-records-core) surfaces. If you want a Claude Code / MCP-client
> integration, start there — it consumes this package's public
> `capsule_ledger.guards`/`capsule_ledger.ledger` API the same way Path 2
> below does, just over MCP instead of in-process.

## Setup (all paths)

```bash
pip install -e ".[dev]"     # installs the `capsule` console script
```

Pick a real ledger directory (not a JSONL fixture) for anything that writes
across multiple process invocations — a fixture gets re-imported into a
throwaway store per CLI call, so writes from a hook wouldn't accumulate:

```bash
mkdir -p /tmp/my-ledger
export CAPSULE_LEDGER=/tmp/my-ledger
```

## Path 1: Goose extension — not yet built

There is no Goose extension, packaged or otherwise, anywhere in this
workspace as of this writing (checked: no `goose` references outside a
generic "MCP-compatible harness" mention in `AGENTS.md`). Goose is
MCP-compatible in principle, and `capsule-engine`'s MCP server is a stdio
server Goose could add via its own stdio MCP extension mechanism — but
this repo doesn't ship a Goose-specific config, and this doc doesn't
include a Goose quickstart because there was no way to drive a real Goose
session in this environment to verify one. Don't infer a config format for
it from this doc; if you're building the real Goose integration, reuse
`capsule-engine`'s MCP server as-is rather than forking it.

## Path 2: Framework adapter (LangGraph / CrewAI / ADK-style)

The public API is `capsule_ledger.guards.GuardEngine.check()` — the same
call an MCP server's `intent_declare` tool would wrap, used in-process
instead of over MCP. This is what belongs inside a LangGraph node, a CrewAI
tool wrapper, or an ADK tool handler, right before (or instead of) letting
the underlying action dispatch:

```python
from capsule_ledger.guards import Action, GuardEngine, LocalSigner

# one-time setup: `guard = GuardEngine(ledger=..., caps_fold=..., signer_provider=...)`
# — see docs/onboarding/framework_adapter_example.py for the full setup.

# --- the two-line integration point, inside your graph/crew/tool node ---
action = Action(verb="send_invoice_reminder", operator="acme-corp", developer="my-agent@v1")
decision = guard.check(action)
# ---------------------------------------------------------------------
```

`docs/onboarding/framework_adapter_example.py` is the full, runnable
version (setup + the two lines above), confirmed against this repo:

```bash
CAPSULE_LEDGER=/tmp/my-ledger python3 docs/onboarding/framework_adapter_example.py
```

```
allow · 48830b95cc65d8815c10536bdd7051f274964a202ad4b6dd2365d84eee7aaedd
```

**Confirm the record landed, and share it:**

```bash
capsule log --ledger /tmp/my-ledger --agent my-agent@v1
capsule verify <id> --ledger /tmp/my-ledger   # an unambiguous prefix is enough
capsule bundle --ledger /tmp/my-ledger --agent my-agent@v1 --out slice.json
capsule verify --bundle slice.json   # re-verifies fully offline, no ledger needed
```

`bundle` also prints a `file://`-safe permalink whose entire payload lives
in the URL fragment — nothing is sent to a server to render it. Add
`--with-viewer` and it also writes a self-contained offline HTML viewer
(no `<script src>`, no external requests) next to `slice.json`.

There is no `capsule_emit`/`capsule-emit` dependency in this integration —
that's a separate repo in this workspace with a different scope; this path
only uses what `capsule-ledger` itself exposes (`capsule_ledger.guards`,
`capsule_ledger.ledger`, `capsule_ledger.folds.catalog`).

## Path 3: Dapr sidecar — not yet built

No Dapr component, binding, or sidecar config exists in this repo, and this
package exposes no HTTP surface a Dapr sidecar could front today (only the
`capsule` CLI and the in-process `capsule_ledger.guards` API). A real Dapr
quickstart would need that HTTP layer built first, not just a component
YAML pointed at nothing. This is flagged as future work rather than
documented with an invented `component.yaml`.

## `capsule agents --status`: honest per-agent state

```bash
capsule agents --status --ledger /tmp/my-ledger --enrolled claude-code@local,my-agent@v1,not-set-up-yet@v1
```

```
≡ capsule agents --status --enrolled claude-code@local,my-agent@v1,not-set-up-yet@v1

claude-code@local
  capturing:  yes · rung: self_attested
  fold 9574753ce2967f281067e0a12d9ae279763ccfe50040e1156eba444f97a21bc6 · records 0–1 · checkpoint #2 · as of just now
  first seen: 2026-08-06T02:31:37.709657Z
  last seen:  2026-08-06T02:31:37.709657Z
  verdicts:   (none):1  (see `capsule log --agent claude-code@local` for the records)

my-agent@v1
  capturing:  yes · rung: self_attested
  fold 9574753ce2967f281067e0a12d9ae279763ccfe50040e1156eba444f97a21bc6 · records 0–1 · checkpoint #2 · as of just now
  first seen: 2026-08-06T02:31:37.911448Z
  last seen:  2026-08-06T02:31:37.911448Z
  verdicts:   (none):1  (see `capsule log --agent my-agent@v1` for the records)

not-set-up-yet@v1
  capturing:  no · declared via --enrolled, no records received yet

Coverage: capturing from 2 of 3 declared agent(s); not yet capturing: not-set-up-yet@v1.
2 agent(s) · as of just now
```

Three properties, on purpose:

- **capturing: yes/no is explicit on every row.** A "yes" row is entirely
  ledger-derived (real records, a real fold-evaluated count). A "no" row
  only ever appears for an agent you named with `--enrolled` — the ledger
  has no notion of agent enrollment on its own (T2's ledger only knows
  about capsules it has actually received), so this command never invents
  one; `--enrolled` is your own out-of-band declaration, cross-checked
  against what's real, and the two are never blended into one unlabeled
  list.
- **rung is the real evidence level** (`assurance.attestation_mode`, read
  off the capsules themselves — currently always `self_attested`, since v0
  has no COSE/asymmetric signer yet, see `guards/signing.py`), not a
  hardcoded label.
- **Coverage is prose, never a percentage** — "capturing from 1 of 2
  declared agent(s)", not "50%".

Omit `--enrolled` and the command still works exactly as before, plus a
`Coverage:` line stating the limitation directly: with no declared list, an
agent that has never sent a record cannot appear on this line at all —
there's nothing to omit-silently since it doesn't exist here yet.

## What's real, what isn't

| Path | Status |
|---|---|
| 1. Goose extension | **Not built.** No Goose-specific code anywhere in this workspace. `capsule-engine`'s MCP server is reusable as-is once someone wires up Goose's own extension config — don't fork it, extend it. |
| 2. Framework adapter | **Real, verified.** `GuardEngine.check()` is the real public API; `docs/onboarding/framework_adapter_example.py` really runs and really appends a capsule. |
| 3. Dapr sidecar | **Not built.** No component/binding config, and no HTTP surface for one to front yet. |
| `capsule agents --status` honest-state | **Real, verified**, including the `--enrolled` fix landed alongside this doc (see `capsule_ledger/cli/agents_cmd.py` and `tests/test_cli_agents.py`). |
