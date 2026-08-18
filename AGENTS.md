# AGENTS.md

This file teaches shell-capable harnesses — Claude Code, Goose, and similar — how to
use the `capsule` CLI to query the ledger, folds, and guards directly. If you can run a
shell command and read its output, you can use this tool with no separate API, no
server to stand up, and no SDK to import.

(If your harness talks MCP instead of a shell, see "MCP instead of shell" at the
bottom — same data, same guarantees, structured tool calls instead of stdout.)

## What this is, in one paragraph

`capsule` is a command-line control plane over a local, append-only ledger of Agent
Action Capsules. Every capsule is a signed, tamper-evident record of an agent
action or a guard decision about one. `capsule` gives you four families of verb: read
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
capsule --version
```

Every ledger-backed verb needs a ledger. Point at one with `--ledger` or set
`$CAPSULE_LEDGER` once per session (legacy `$ASG_LEDGER` is still honored as a
fallback):

```bash
export CAPSULE_LEDGER=tests/fixtures/sample_ledger.jsonl   # or a real LedgerStore directory
```

`--ledger` accepts either a `LedgerStore` root (a directory) or a bare JSONL file
(a fixture, or an export from another tool) — a JSONL file is imported into a
throwaway store for the duration of the command, so every fixture under
`tests/fixtures/` works directly with no separate import step.

## The verbs

### `capsule log` — list records matching a filter (git-log style)

```bash
capsule log --ledger $CAPSULE_LEDGER --agent procurement-agent@v1 --since 2026-08-01
```

Flags (all optional, all composable): `--agent` (developer id), `--since`/`--until`
(inclusive ISO-8601 timestamp bounds), `--counterparty` (operator), `--verdict`
(`disposition.verdict_class`), `--action-type`, `--limit`. Prints one block per
matching capsule (agent, operator, verdict, date, action summary) and a footer
line that always states both the filtered count *and* the ledger's true total —
`capsule` never lets a filtered view pass itself off as the whole ledger. If a
capsule's `chain.parent_capsule_id` isn't in the ledger, the footer says so
(`N chain gap(s) detected`) instead of falsely claiming an unbroken sequence.

**This is the verb for "what did my agents do" questions.** `capsule log --agent X`
answers "what did agent X do"; add `--since`/`--until` for a time window
("...last night", "...this week").

### `capsule show <capsule_id>` — full detail on one record (git-show style)

```bash
capsule show 705955419ca6f944a75db77ae2a59844fdd99d355866c6c1dbc4ebe655c024c7
capsule show 70595541 --json   # an unambiguous prefix is enough; --json for raw output
```

Prints agent, operator, action, verdict, assurance mode, chain parent (if any),
and the full constraints breakdown (`id: result` for every check that ran). This
is the verb for "why was this decision what it was" — the constraints list *is*
the explanation; there's no separate reasoning to fetch.

### `capsule verify` — verify one record or a whole bundle, offline

```bash
capsule verify <capsule_id> --ledger $CAPSULE_LEDGER
capsule verify --bundle bundle.json         # re-verify a self-contained slice, no ledger needed
```

Exit codes are meaningful, not decorative: `0` verified clean, `1` verification
failed (digest mismatch, broken chain — a real tamper finding), `2` usage error
(bad args, capsule/bundle not found). Script against these codes rather than
grepping stdout. `--json` gives you the findings list as structured data
(`code`/`detail`/`severity` per finding).

### `capsule bundle` — a self-contained, independently verifiable slice

```bash
capsule bundle --ledger $CAPSULE_LEDGER --agent procurement-agent@v1 --out slice.json
```

Takes the same filter flags as `log`, plus `--out` (default `bundle.json`) and
`--verify-base-url` (default `https://verify.agentactioncapsule.org/bundle`).
Pulls in any cited `chain.parent_capsule_id` transitively, so the slice verifies
standalone — hand `slice.json` to someone with no access to your ledger and
`capsule verify --bundle slice.json` still works. Also prints a `file://`-safe
permalink whose entire payload lives in the URL fragment (after `#`) — nothing
is ever sent to a server to render or check it.

Add `--with-viewer` (or `--viewer-out <path>` to name it explicitly) to also
write a self-contained HTML recipient viewer next to `--out` (default:
`--out` with a `.html` extension) — no `<script src>`, no external requests,
opens and verifies on a machine with no network at all. The bundle's own
JSON/fragment is byte-identical whether or not this flag is passed; the
viewer only ever rides alongside it.

### `capsule fold` — the declarative-aggregate catalog

```bash
capsule fold list                                   # what's defined, and its content digest
capsule fold test spend.weekly/1.0.0 --ledger $CAPSULE_LEDGER --key procurement-agent@v1 --as-of 2026-08-01T00:00:00Z
capsule fold lint path/to/my-fold.yaml              # validate a definition file before adding it
capsule fold new my.custom.fold/1.0.0               # scaffold a new definition
```

Folds are how this system computes any number that matters (spend, counts,
last-decision) — replayed deterministically over the ledger, never computed ad
hoc. `fold test` prints the full result envelope
(`fold <digest> · records N–M · checkpoint #X · as of <staleness>`), so a fold
result is always accompanied by exactly what range and checkpoint it was
computed against. `--dir` overrides the catalog directory on any fold verb
(default: the built-in catalog, or `$CAPSULE_FOLD_DIR`). Rolling-window folds
require `--as-of` — this CLI (like the fold engine underneath it) refuses to
invent a time anchor from the wall clock; you supply one derived from real data.

**Ask `capsule fold list` before asking a numeric question** — it tells you what's
already defined (e.g. `spend.weekly/1.0.0`, `actions.count_by_developer/1.0.0`)
so you evaluate an existing fold instead of trying to derive a number yourself
from raw `log` output.

### `capsule constraints list` — what's actually enforced

```bash
capsule constraints list
```

No `--ledger` needed — this is a static catalog, not a ledger query. Prints
every registered guard check (`dedupe`, `caps`, `verify_before_dispatch`) with
its method, plus the action-class taxonomy (`money.transfer`, `data.delete`,
`comms.external`, `info.query`, and the fail-closed `unclassified` default)
with each class's `consequential`/`fail_open_allowed` flags. **Ask this before
asking whether some action would be allowed** — it's the ground truth for what
gates exist, without needing to read guard source.

### `capsule agents --status` — per-agent summary

```bash
capsule agents --status --ledger $CAPSULE_LEDGER
```

One block per agent seen in the ledger: a real fold-evaluated record count (not
a number this command invents), first/last seen timestamps, and a verdict
breakdown, plus a pointer to the exact `capsule log --agent <id>` invocation that
shows the underlying records. This is the fastest way to answer "which agents
have been active, and how much."

### `capsule guard dry-run` — replay a ledger through the guard checks

```bash
capsule guard dry-run --ledger $CAPSULE_LEDGER --since 7d --cap money.transfer=10000000 --out report.html --share
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
reproducible). Prints `evaluated under manifest <digest>` when a policy
manifest resolves (the default; `--no-manifest` skips it) — see below.

### `capsule manifest show|activate|verify` — declare-attest-verify for guard policy

```bash
capsule manifest show                                             # resolve + print the digest
capsule manifest activate --ledger $CAPSULE_LEDGER --operator acme --developer ops
capsule manifest verify --ledger $CAPSULE_LEDGER --capsule <decision-capsule-id>
```

A policy manifest is one file listing the active fold and wicket ("wicket" =
this workspace's name for a guard constraint — `dedupe`/`caps`/
`verify_before_dispatch`) definitions *by digest* — a lockfile, never a copy.
`show` resolves it against the real fold/wicket catalogs and fails closed if
any pinned digest has drifted from what's actually there now. `activate`
appends a signed, passive config-change record (`chain.relation=epoch_opens`,
chained to the ledger's previous activation if any) citing the manifest's own
digest — this *is* the adoption event. Every decision `GuardEngine.check()`
makes while configured with a manifest's digest carries that same digest on
`asg_payload.manifest_digest`, so "which policy governed this decision" is
checkable directly off the capsule; `verify` confirms a given decision
capsule's cited digest actually resolves to a real, loadable manifest.
`capsule diff` renders a manifest activation as a distinct "manifest boundary
event", never silently folded into an ordinary added-record count.

### Reserved, not yet implemented

`capsule diff`, `capsule blame`, `capsule bisect` print a clear "not yet implemented" message
and exit `1`. The verb names are reserved so scripts and docs referencing them
don't silently typo into a shell error; don't build against them yet.

## Environment variables

| Variable | Used by | Meaning |
|---|---|---|
| `$CAPSULE_LEDGER` | every ledger-backed verb | default `--ledger` |
| `$CAPSULE_FOLD_DIR` | `fold`, `constraints list`, `agents --status`, `guard dry-run`, `manifest` | default fold catalog directory (falls back to the built-in catalog) |
| `$CAPSULE_WICKET_DIR` | `guard dry-run`, `manifest` | default wicket catalog directory (falls back to the built-in catalog) |
| `$CAPSULE_VERIFY_BASE_URL` | `bundle` | base URL the verify permalink's fragment is appended to |

Legacy `$ASG_*` names (`ASG_LEDGER`, `ASG_FOLD_DIR`, `ASG_WICKET_DIR`,
`ASG_VERIFY_BASE_URL`, and their MCP/telemetry equivalents) are still honored
as a fallback when the `CAPSULE_*` name isn't set.

## Reading the output

Two conventions repeat across every verb, deliberately:

- **The envelope line** — `fold <digest> · records N–M · checkpoint #X · as of
  <staleness>` — appears wherever a fold result is shown. `<digest>` is the
  fold *definition's* own content digest, not a name any command invents;
  `N–M` and `#X` pin exactly what range and ledger size produced the number.
  Never quote a fold result without this line attached.
- **The CLI echo** — every command prints a `≡ capsule <verb> <flags…>` line, in a
  fixed flag order regardless of the order you typed them. This is the
  canonical, copy-pasteable form of the query that produced the output above
  it — reuse it verbatim when reporting a result back to a user, so they can
  re-run exactly what you ran.

## Practical playbook

- **"What did my agents do last night?"** → `capsule log --agent <id> --since
  <timestamp>` (or `capsule agents --status` first if you don't know which agent).
- **"How much budget is left?"** → `capsule fold test spend.weekly/1.0.0 --ledger
  $CAPSULE_LEDGER --key <agent> --as-of <now>`, then compare the envelope's
  `result` against the configured cap (`capsule constraints list` shows the caps
  check's method; the cap value itself is a deployment-specific
  `--cap CLASS=MINOR_UNITS`, not baked into the fold).
- **"Why was this refused?"** → `capsule show <capsule_id>` — the constraints
  block *is* the answer; look for the check with `result: fail`.
- **"Has this already happened?"** → `capsule log --agent <id> --action-type
  <type>` and scan for a matching action, or run `capsule guard dry-run` if you
  want the dedupe check's own verdict on a historical ledger rather than
  reading records by hand.
- **"Is this ledger intact?"** → `capsule verify <capsule_id>` for one record,
  or `capsule bundle` + `capsule verify --bundle` for a slice you want to hand off.
- **"What's enforced here?"** → `capsule constraints list`, always, before you
  assume a guard exists or a class is fail-open.

## MCP instead of shell

If your harness speaks MCP (Model Context Protocol) rather than driving a
shell, `capsule_ledger.mcp.server` exposes the same ledger, folds, and guard
checks as structured tools instead of CLI stdout — every read tool's response
carries the same envelope shape described above, so an MCP-connected agent
gets identical verification guarantees to one running the CLI directly. See
`capsule_ledger/mcp/server.py` for the tool catalog and
[`docs/onboarding.md`](docs/onboarding.md) for wiring it up as a stdio server
(Claude Code's `.mcp.json`/hook config, verified end to end) or your own
harness's own MCP config. The one tool that writes —
`intent.declare` — is the only place either interface ever appends to the
ledger; everything else, CLI or MCP, is read-only.
