# Onboarding: hooking an agent up to capsule-ledger

Four ways to connect an agent (or an agent framework) to a capsule-ledger
instance. Every command below was run against this repo's real code before
it was written down here — none of it is illustrative pseudocode. Two of
the four paths (Goose, Dapr) don't have real integration code in this repo
yet; those sections say so plainly instead of inventing a package or a
config format that doesn't exist. See "What's real, what isn't" at the
bottom for the honest scorecard.

Each path below ends the same way: a real record lands in a real ledger,
and you confirm it with a *different* tool than the one that wrote it
(`capsule log` / `capsule verify`) — because a write path that only checks
itself isn't verification.

## Setup (all paths)

```bash
pip install -e ".[dev]"     # installs the `capsule` and `capsule-mcp` console scripts
```

Pick a real ledger directory (not a JSONL fixture) for anything that writes
across multiple process invocations — a fixture gets re-imported into a
throwaway store per CLI call, so writes from a hook or an MCP session
wouldn't accumulate:

```bash
mkdir -p /tmp/my-ledger
export CAPSULE_LEDGER=/tmp/my-ledger
```

## Path 1: Claude Code — MCP server + a capture hook

`capsule-mcp` (console script: `capsule_ledger.mcp.server:main`) is a real,
tested MCP server (nine read tools, plus `intent_declare` — the only tool
that writes). Two ways to wire it into Claude Code:

**A. As an MCP server**, so the agent can call `intent_declare` (and every
read tool) directly during a session. Add to `.mcp.json` in your project
(format per Claude Code's stdio-server config):

```json
{
  "mcpServers": {
    "capsule-mcp": {
      "type": "stdio",
      "command": "capsule-mcp",
      "env": { "CAPSULE_LEDGER": "/tmp/my-ledger" }
    }
  }
}
```

**B. As a capture hook**, so every matched tool call is recorded whether or
not the agent decides to call `intent_declare` itself. Add to
`.claude/settings.json`:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "*",
        "hooks": [
          { "type": "command", "command": "python3 docs/onboarding/claude_code_hook.py" }
        ]
      }
    ]
  }
}
```

`docs/onboarding/claude_code_hook.py` is a real, runnable script (not a
snippet) — it reads the hook's stdin JSON, opens a stdio session to
`capsule-mcp`, and calls `intent_declare`. Confirmed end to end, standing in
for what Claude Code itself would pipe in on a `PostToolUse` event:

```bash
echo '{"cwd":"'"$PWD"'","tool_name":"Bash","tool_input":{"command":"npm test"}}' \
  | CAPSULE_LEDGER=/tmp/my-ledger python3 docs/onboarding/claude_code_hook.py
```

```
capsule-ledger: allow · bc9abfc742dcbd194c7aac3075e7c84c2411e7502b7819ba4adb1c63ea6412a0
```

**Confirm the record landed** (a different tool than the one that wrote it):

```bash
capsule log --ledger /tmp/my-ledger --agent claude-code@local
capsule verify bc9abfc7 --ledger /tmp/my-ledger   # an unambiguous prefix is enough
```

```
✓ verifies · bc9abfc742dcbd194c7aac3075e7c84c2411e7502b7819ba4adb1c63ea6412a0
```

**Something shareable:**

```bash
capsule bundle --ledger /tmp/my-ledger --agent claude-code@local --out slice.json
capsule verify --bundle slice.json   # re-verifies fully offline, no ledger needed
```

`bundle` also prints a `file://`-safe permalink whose entire payload lives
in the URL fragment — nothing is sent to a server to render it.

**Backend seam, for an alternate/remote backend implementation.** `capsule-mcp`
is wired to a local `LedgerStore` by default, but the server itself doesn't
know or care where its `LedgerAPI` binding comes from — that's `open_backend`'s
job (see its own docstring in `capsule_ledger/mcp/config.py` for the contract).
`capsule_ledger.mcp` re-exports `ServerConfig`, `load_config`, and
`open_backend` from its public surface:

```python
from capsule_ledger.mcp import ServerConfig, load_config, open_backend
```

An implementation reusing `capsule_ledger.mcp.server` with a different
`LedgerAPI` binding (e.g. a hosted/paid backend) should depend on this public
import, not reach into `capsule_ledger.mcp.config` directly.

Handing the slice to someone without assuming they have network? Add
`--with-viewer`: alongside `slice.json` it writes `slice.html`, a
self-contained recipient viewer (no `<script src>`, no external requests)
that opens and verifies on any machine, no server or network required on
either end.

```bash
capsule bundle --ledger /tmp/my-ledger --out slice.json --with-viewer
open slice.html   # or hand the whole folder over — it verifies itself
```

## Path 2: Goose extension — not yet built

There is no Goose extension, packaged or otherwise, anywhere in this
workspace as of this writing (checked: no `goose` references outside a
generic "MCP-compatible harness" mention in `AGENTS.md`/`mcp/config.py`'s
docstrings). Goose is MCP-compatible in principle — `capsule-mcp` is the
same stdio server Path 1 uses, and Goose has its own way of adding a stdio
MCP extension — but this repo doesn't ship a Goose-specific config, and
this doc doesn't include a Goose quickstart because there was no way to
drive a real Goose session in this environment to verify one. Don't infer a
config format for it from this doc; if you're building the real Goose
integration, reuse `capsule-mcp` as-is rather than forking it.

## Path 3: Framework adapter (LangGraph / CrewAI / ADK-style)

The public API is `capsule_ledger.guards.GuardEngine.check()` — the same call
`capsule-mcp`'s `intent_declare` tool wraps, used in-process instead of over
MCP. This is what belongs inside a LangGraph node, a CrewAI tool wrapper, or
an ADK tool handler, right before (or instead of) letting the underlying
action dispatch:

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

**Confirm the record landed, and share it** — identical to Path 1 from here
on: `capsule log --ledger /tmp/my-ledger --agent my-agent@v1`, `capsule
verify <id>`, `capsule bundle`.

There is no `capsule_emit`/`capsule-emit` dependency in this integration —
that's a separate repo in this workspace with a different scope; this path
only uses what `capsule-ledger` itself exposes (`capsule_ledger.guards`,
`capsule_ledger.ledger`, `capsule_ledger.folds.catalog`).

## Path 4: Dapr sidecar — not yet built

No Dapr component, binding, or sidecar config exists in this repo. The MCP
server only speaks stdio (see `mcp/server.py`) — there is no HTTP-exposed
surface a Dapr sidecar could front today, so a real Dapr quickstart would
need that HTTP layer built first, not just a component YAML pointed at
nothing. This is flagged as future work rather than documented with an
invented `component.yaml`.

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
| 1. Claude Code (MCP server + hook) | **Real, verified.** `capsule-mcp` is a real console script; `docs/onboarding/claude_code_hook.py` really runs and really appends a capsule; every command above was executed against this repo. |
| 2. Goose extension | **Not built.** No Goose-specific code anywhere in this workspace. `capsule-mcp` is reusable as-is once someone wires up Goose's own extension config — don't fork it, extend it. |
| 3. Framework adapter | **Real, verified.** `GuardEngine.check()` is the real public API; `docs/onboarding/framework_adapter_example.py` really runs and really appends a capsule. |
| 4. Dapr sidecar | **Not built.** No component/binding config, and no HTTP surface for one to front yet. |
| `capsule agents --status` honest-state | **Real, verified**, including the `--enrolled` fix landed alongside this doc (see `capsule_ledger/cli/agents_cmd.py` and `tests/test_cli_agents.py`). |
