# AGENTS.md

This file teaches shell-capable harnesses — Claude Code, Goose, and similar — how to
use the `asg` CLI to query the ledger, folds, and guards directly. If you can run a
shell command and read its output, you can use this tool with no separate API, no
server to stand up, and no SDK to import.

(If your harness talks MCP instead of a shell, see "MCP instead of shell" at the
bottom — same data, same guarantees, structured tool calls instead of stdout.)

## What this is, in one paragraph

`asg` is a command-line control plane over a local, append-only ledger of Agent
Action Capsules. Every capsule is a signed, tamper-evident record of an agent
action or a guard decision about one. `asg` gives you four families of verb: read
the ledger (`log`/`show`), verify it (`verify`/`bundle`), replay declared
aggregates over it (`fold`), and inspect what's enforced (`constraints`/`agents`/
`guard dry-run`). Every numeric answer this CLI prints carries its own proof —
a fold envelope (`fold <digest> · records N–M · checkpoint #X · as of <staleness>`)
or a verification result — never a bare number you have to trust. If you're
tempted to `cat` a ledger file and eyeball it, use the CLI instead: it enforces
determinism rules (no floats, no wall-clock windows, ledger-order-only replay)
that a hand-rolled `grep`/`jq` pipeline will silently violate.

## Setup

```bash
pip install -e ".[dev]"
asg --version
```

Every ledger-backed verb needs a ledger. Point at one with `--ledger` or set
`$ASG_LEDGER` once per session:

```bash
export ASG_LEDGER=tests/fixtures/sample_ledger.jsonl   # or a real LedgerStore directory
```

`--ledger` accepts either a `LedgerStore` root (a directory) or a bare JSONL file
(a fixture, or an export from another tool) — a JSONL file is imported into a
throwaway store for the duration of the command, so every fixture under
`tests/fixtures/` works directly with no separate import step.

## The verbs

### `asg log` — list records matching a filter (git-log style)

```bash
asg log --ledger $ASG_LEDGER --agent procurement-agent@v1 --since 2026-08-01
```

Flags (all optional, all composable): `--agent` (developer id), `--since`/`--until`
(inclusive ISO-8601 timestamp bounds), `--counterparty` (operator), `--verdict`
(`disposition.verdict_class`), `--action-type`, `--limit`. Prints one block per
matching capsule (agent, operator, verdict, date, action summary) and a footer
line that always states both the filtered count *and* the ledger's true total —
`asg` never lets a filtered view pass itself off as the whole ledger. If a
capsule's `chain.parent_capsule_id` isn't in the ledger, the footer says so
(`N chain gap(s) detected`) instead of falsely claiming an unbroken sequence.

**This is the verb for "what did my agents do" questions.** `asg log --agent X`
answers "what did agent X do"; add `--since`/`--until` for a time window
("...last night", "...this week").

### `asg show <capsule_id>` — full detail on one record (git-show style)

```bash
asg show 705955419ca6f944a75db77ae2a59844fdd99d355866c6c1dbc4ebe655c024c7
asg show 70595541 --json   # an unambiguous prefix is enough; --json for raw output
```

Prints agent, operator, action, verdict, assurance mode, chain parent (if any),
and the full constraints breakdown (`id: result` for every check that ran). This
is the verb for "why was this decision what it was" — the constraints list *is*
the explanation; there's no separate reasoning to fetch.

### `asg verify` — verify one record or a whole bundle, offline

```bash
asg verify <capsule_id> --ledger $ASG_LEDGER
asg verify --bundle bundle.json         # re-verify a self-contained slice, no ledger needed
```

Exit codes are meaningful, not decorative: `0` verified clean, `1` verification
failed (digest mismatch, broken chain — a real tamper finding), `2` usage error
(bad args, capsule/bundle not found). Script against these codes rather than
grepping stdout. `--json` gives you the findings list as structured data
(`code`/`detail`/`severity` per finding).

### `asg bundle` — a self-contained, independently verifiable slice

```bash
asg bundle --ledger $ASG_LEDGER --agent procurement-agent@v1 --out slice.json
```

Takes the same filter flags as `log`, plus `--out` (default `bundle.json`) and
`--verify-base-url` (default `https://verify.agentactioncapsule.org/bundle`).
Pulls in any cited `chain.parent_capsule_id` transitively, so the slice verifies
standalone — hand `slice.json` to someone with no access to your ledger and
`asg verify --bundle slice.json` still works. Also prints a `file://`-safe
permalink whose entire payload lives in the URL fragment (after `#`) — nothing
is ever sent to a server to render or check it.

### `asg fold` — the declarative-aggregate catalog

```bash
asg fold list                                   # what's defined, and its content digest
asg fold test spend.weekly/1.0.0 --ledger $ASG_LEDGER --key procurement-agent@v1 --as-of 2026-08-01T00:00:00Z
asg fold lint path/to/my-fold.yaml              # validate a definition file before adding it
asg fold new my.custom.fold/1.0.0               # scaffold a new definition
```

Folds are how this system computes any number that matters (spend, counts,
last-decision) — replayed deterministically over the ledger, never computed ad
hoc. `fold test` prints the full result envelope
(`fold <digest> · records N–M · checkpoint #X · as of <staleness>`), so a fold
result is always accompanied by exactly what range and checkpoint it was
computed against. `--dir` overrides the catalog directory on any fold verb
(default: the built-in catalog, or `$ASG_FOLD_DIR`). Rolling-window folds
require `--as-of` — this CLI (like the fold engine underneath it) refuses to
invent a time anchor from the wall clock; you supply one derived from real data.

**Ask `asg fold list` before asking a numeric question** — it tells you what's
already defined (e.g. `spend.weekly/1.0.0`, `actions.count_by_developer/1.0.0`)
so you evaluate an existing fold instead of trying to derive a number yourself
from raw `log` output.

### `asg constraints list` — what's actually enforced

```bash
asg constraints list
```

No `--ledger` needed — this is a static catalog, not a ledger query. Prints
every registered guard check (`dedupe`, `caps`, `verify_before_dispatch`) with
its method, plus the action-class taxonomy (`money.transfer`, `data.delete`,
`comms.external`, `info.query`, and the fail-closed `unclassified` default)
with each class's `consequential`/`fail_open_allowed` flags. **Ask this before
asking whether some action would be allowed** — it's the ground truth for what
gates exist, without needing to read guard source.

### `asg agents --status` — per-agent summary

```bash
asg agents --status --ledger $ASG_LEDGER
```

One block per agent seen in the ledger: a real fold-evaluated record count (not
a number this command invents), first/last seen timestamps, and a verdict
breakdown, plus a pointer to the exact `asg log --agent <id>` invocation that
shows the underlying records. This is the fastest way to answer "which agents
have been active, and how much."

### `asg guard dry-run` — replay a ledger through the guard checks

```bash
asg guard dry-run --ledger $ASG_LEDGER --since 7d --cap money.transfer=10000000 --out report.html --share
```

Replays every record through the same three reference checks `GuardEngine.check`
runs live (`dedupe`, `caps`, `verify_before_dispatch`), without ever appending
anything — a what-if over history, not a new decision. `--cap CLASS=MINOR_UNITS`
configures per-action-class caps (repeatable; an unconfigured class never
triggers the caps guard). `--since` is a rolling window anchored to the ledger's
own latest record (`7d`, or `all` for no filter). Writes a self-contained HTML
report whose data lives only in the URL fragment; `--share` prints the full
shareable link, `--verify` re-replays and re-verifies every cited capsule before
exiting (use this in CI to catch a report that quietly stopped being
reproducible).

### Reserved, not yet implemented

`asg diff`, `asg blame`, `asg bisect` print a clear "not yet implemented" message
and exit `1`. The verb names are reserved so scripts and docs referencing them
don't silently typo into a shell error; don't build against them yet.

## Environment variables

| Variable | Used by | Meaning |
|---|---|---|
| `$ASG_LEDGER` | every ledger-backed verb | default `--ledger` |
| `$ASG_FOLD_DIR` | `fold`, `constraints list`, `agents --status`, `guard dry-run` | default fold catalog directory (falls back to the built-in catalog) |
| `$ASG_VERIFY_BASE_URL` | `bundle` | base URL the verify permalink's fragment is appended to |

## Reading the output

Two conventions repeat across every verb, deliberately:

- **The envelope line** — `fold <digest> · records N–M · checkpoint #X · as of
  <staleness>` — appears wherever a fold result is shown. `<digest>` is the
  fold *definition's* own content digest, not a name any command invents;
  `N–M` and `#X` pin exactly what range and ledger size produced the number.
  Never quote a fold result without this line attached.
- **The CLI echo** — every command prints a `≡ asg <verb> <flags…>` line, in a
  fixed flag order regardless of the order you typed them. This is the
  canonical, copy-pasteable form of the query that produced the output above
  it — reuse it verbatim when reporting a result back to a user, so they can
  re-run exactly what you ran.

## Practical playbook

- **"What did my agents do last night?"** → `asg log --agent <id> --since
  <timestamp>` (or `asg agents --status` first if you don't know which agent).
- **"How much budget is left?"** → `asg fold test spend.weekly/1.0.0 --ledger
  $ASG_LEDGER --key <agent> --as-of <now>`, then compare the envelope's
  `result` against the configured cap (`asg constraints list` shows the caps
  check's method; the cap value itself is a deployment-specific
  `--cap CLASS=MINOR_UNITS`, not baked into the fold).
- **"Why was this refused?"** → `asg show <capsule_id>` — the constraints
  block *is* the answer; look for the check with `result: fail`.
- **"Has this already happened?"** → `asg log --agent <id> --action-type
  <type>` and scan for a matching action, or run `asg guard dry-run` if you
  want the dedupe check's own verdict on a historical ledger rather than
  reading records by hand.
- **"Is this ledger intact?"** → `asg verify <capsule_id>` for one record,
  or `asg bundle` + `asg verify --bundle` for a slice you want to hand off.
- **"What's enforced here?"** → `asg constraints list`, always, before you
  assume a guard exists or a class is fail-open.

## MCP instead of shell

If your harness speaks MCP (Model Context Protocol) rather than driving a
shell, `asg_ledger.mcp.server` exposes the same ledger, folds, and guard
checks as structured tools instead of CLI stdout — every read tool's response
carries the same envelope shape described above, so an MCP-connected agent
gets identical verification guarantees to one running the CLI directly. See
`asg_ledger/mcp/server.py` for the tool catalog and `docs/` (or your harness's
own MCP config) for wiring it up as a stdio server. The one tool that writes —
`intent.declare` — is the only place either interface ever appends to the
ledger; everything else, CLI or MCP, is read-only.
