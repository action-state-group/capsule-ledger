# asg-ledger — batch 1 status

Tracking file for `tasks/eng-tasks-batch1-2026-08-04.md`. Replaces the asg/inbox.md +
outbox.md pattern for this repo only — coders working here report status by editing
this file directly (append under their task's row) and opening a PR against `main`.

Dependency order: T0 → (T1 ∥ T2 ∥ T7) → T3 → (T4 ∥ T5 ∥ T6). T7 and T8 are independent.

| Task | Status | Branch / PR | Notes |
|---|---|---|---|
| T0 | claimed | — | scaffold, blocks T1-T6 |
| T1 | blocked | — | needs T0 |
| T2 | blocked | — | needs T0 |
| T3 | blocked | — | needs T1 + T2 |
| T4 | blocked | — | needs T2 (folds via T1) |
| T5 | blocked | — | needs T4 (API via T1/T2) |
| T6 | blocked | — | needs T3 |
| T7 | claimed | — | independent, agentactioncapsule-site |
| T8 | blocked | — | independent but held for PM co-owned thresholds doc — not spawned yet, see note |

**T8 note:** the task says "Thresholds doc is written BEFORE distribution... Steven
writes the thresholds." Not spawning T8 yet — needs Steven to confirm the
thresholds doc exists or that instrumentation-drafting can proceed ahead of it.

## Protocol (this repo only)
- Claim a task by editing its row above before starting (avoid two writers).
- Report completion by appending a dated note under the relevant task row + a link
  to the PR. Manager (terminal orchestrator) reviews and updates Status to `done`.
- Blocking questions or spec-adjacent findings (vocabulary gaps, design conflicts)
  go under a `## Needs decision` section below — same discipline as asg/outbox.md.
- PRs stay open for review; merge gate is the operator (Steven) unless stated otherwise.

## Needs decision

_(none yet)_
