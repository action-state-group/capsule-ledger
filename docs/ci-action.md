# `guard-check` GitHub Action

A composite GitHub Action, shipped from this repo, for **other** repos to
run in their own CI: pre-merge policy lint + regression replay + epoch-diff
for a `capsule-ledger` guard config.

## Honesty line — read this before wiring it in

**This Action catches policy errors PRE-MERGE. The runtime `GuardEngine`
wired into your own integration enforces LIVE limits.** `guard-check` is a
linter and a regression-catcher that runs against fixtures and snapshots in
CI — it never sees, and cannot gate, your production traffic. A green
`guard-check` run tells you your guard config is well-formed and behaves
the same way it did against your fixture ledger; it does not tell you your
live agents are being guarded. That's the job of `GuardEngine.check(...)`
running inside your own agent-action integration, in `dry_run=False` mode.
Do not let a green check here stand in for that.

## What it does

`guard-check` installs `capsule-ledger` (from its own pinned checkout, so
the CLI logic matches the action's own ref exactly — no separate version to
drift) and runs three independent, individually-optional steps, each a thin
wrapper over the real CLI command — no policy logic is reimplemented in the
Action itself:

1. **Policy lint** — `capsule constraints list` (always), and, if `fold-dir`
   is given, `capsule fold list --dir <fold-dir>` to validate every fold
   definition backing your guard config (e.g. the caps check's spend fold)
   parses and type-checks. Fails the check on any malformed definition.
2. **Dry-run replay** — `capsule guard dry-run --ledger <guard-ledger>
   --verify`, replaying a snapshot ledger fixture through the real guard
   engine. `--verify` re-replays and re-derives the report, confirming it's
   reproducible and that every cited capsule independently re-verifies.
   Fails the check on any mismatch — the same regression-catching logic
   `capsule guard dry-run --verify` already ships, not a reimplementation.
3. **Epoch-diff** — `capsule diff <diff-from> <diff-to> --ledger
   <diff-ledger>`, reusing the real epoch-diff/checkpoint-diff logic in
   [`asg_ledger/cli/diff_cmd.py`](../asg_ledger/cli/diff_cmd.py) unchanged.
   Prints the added/removed records and verdict-distribution delta to the
   job log and `$GITHUB_STEP_SUMMARY`, and fails the check if either ref is
   unresolvable.

Each step is skipped (not run) if its required input isn't supplied, so a
downstream repo can adopt just the lint, just the dry-run, just the diff, or
all three.

## Usage

```yaml
# .github/workflows/guard-check.yml in a DOWNSTREAM repo
name: guard-check
on: [pull_request]

jobs:
  guard-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: action-state-group/capsule-ledger/.github/actions/guard-check@main
        with:
          fold-dir: guard/catalog          # your fold catalog directory
          guard-ledger: fixtures/snapshot.jsonl
          cap: |
            money.transfer=10000000
            data.delete=0
          diff-ledger: fixtures/snapshot.jsonl
          diff-from: '1'
          diff-to: HEAD
```

Pin to a release tag or commit SHA instead of `@main` for anything beyond
experimentation.

### Inputs

See [`.github/actions/guard-check/action.yml`](../.github/actions/guard-check/action.yml)
for the full, current list with descriptions — `fold-dir`, `guard-ledger`,
`since`, `cap`, `diff-ledger`, `diff-from`, `diff-to`, `diff-fold`,
`diff-key`, `python-version`.

### Outputs

- `dry-run-report` — path to the self-contained HTML dry-run report (empty
  if the dry-run step was skipped).
- `diff-json` — path to the JSON epoch-diff output (empty if the epoch-diff
  step was skipped).

## Proven, not just declared

This repo dogfoods `guard-check` against its own fixtures in
[`.github/workflows/guard-check-selftest.yml`](../.github/workflows/guard-check-selftest.yml):
one job runs the happy path and asserts both outputs actually exist and are
non-trivial; a second job runs the action against a deliberately malformed
fold catalog and an unresolvable diff ref, and asserts both fail the check
outcome (`failure`, not `success`) — proving the check actually rejects bad
input rather than passing everything through.
