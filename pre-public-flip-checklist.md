# Pre-Public Flip Checklist — capsule-ledger

Date verified: 2026-08-17  
Verifier: coder-flip-hygiene (coder pass; manager review required before flip)

**Flip itself is Steven's click. This checklist clears the hygiene prerequisites.**

---

## 1. Neutrality scan — reserved vocabulary

**Status: ✅ CLEAN on the branch under review**

The `.github/neutrality_scan.py` gate uses `rglob("*")` on the repo root (not
`git ls-files`), so untracked directories ARE scanned. The 2026-08-17 pre-flip sweep
found three hits — all inside `.venv/site-packages/` (untracked, never committed).

Fix applied in this branch:
- Added `.venv/` to `.gitignore` (prevents future accidental commit).

**Manual step before flip (Steven):** delete the canonical `.venv/` directory from the
working tree (`rm -rf capsule-ledger/.venv`) before running the gate in CI. A gitignored
directory is still scanned; deleting it is what makes the gate green. The worktree used
for this branch has no `.venv/` and the gate is clean there.

CI context: the `NEUTRALITY_TERMS` secret is required; the gate exits 2 (misconfiguration)
without it — configure the secret in repo settings before flipping.

---

## 2. Ghost package directory — `asg_ledger/`

**Status: ✅ NOT PRESENT on this branch / in worktree**

The pre-rename skeleton `asg_ledger/` (empty subdirectory tree: cli, console, folds,
guards, ledger, lenses, mcp, mmr, policy, report, telemetry, vectors) exists in the
canonical working tree as an untracked ghost. It has zero files and zero git objects —
`git status` does not report it; `git ls-files asg_ledger/` is empty.

**Manual step before flip (Steven):** `rm -rf capsule-ledger/asg_ledger/` and its
companion `capsule-ledger/asg_ledger.egg-info/` from the canonical working tree. These
are untracked; they do not need `git rm`. They cannot be committed into this branch
because they contain no files.

Companion artifact: `asg_ledger.egg-info/` exists in the canonical checkout (stale
editable-install artifact from before the rename). Delete it alongside `asg_ledger/`.

E2e test note: the inbox task references `test_bundle_e2e_capsule_ledger.py` as a test
that SKIPs due to the ghost. That file does not exist in the test suite. No skip guard
was found that references `asg_ledger`. The existing bundle tests in `test_cli_bundle.py`
(3 tests) run and pass without the ghost directory. The package discovery test in
`test_package.py` imports `capsule_ledger` (not `asg_ledger`) and passes. No skip
condition is attributable to the ghost at this time; the inbox note is recorded but
unverified.

---

## 3. Remote / repo mismatch

**Status: ✅ RESOLVED — documented**

Local `origin` URL: `git@github.com:action-state-group/capsule-ledger.git`

That repo returns 404 when accessed while the repo is private. This is expected: the
repo exists but is private; unauthenticated reads 404. Wave-1 PRs #36–#40 are confirmed
against `action-state-group/capsule-ledger` (same remote). The flip target and the PR
home are the same repo; there is no mismatch.

**Before flip:** confirm the repo visibility setting shows Private in GitHub settings,
and that it reads Public after Steven's flip click. No URL change is needed.

---

## 4. History squash (capsule-anchor precedent)

**Status: 🟡 PENDING — Steven's action**

The capsule-anchor precedent (2026-06-25): squash to a single clean commit at flip so
dev history — which grew up next to private repos — does not travel publicly.

**This is Steven's click.** Do not merge this branch to main and push; that would expose
the uncompressed dev history. Instead:
1. Steven merges the hygiene work to main.
2. Steven squash-resets main to a single commit before making the repo public.
3. Steven flips the visibility.

This branch (`ldg-flip-hygiene-public-repo`) contains only hygiene commits and is safe
to merge as-is. The squash of the full main history is a separate step.

---

## 5. Wave-1 PRs (#36–#40) merge status

**Status: 🟡 PENDING — Steven's action**

Five PRs built 2026-08-12 are NOT yet merged to main. Latest commit on main at checklist
time: `e2654c2` (PR #29). The hygiene task can complete and this branch can merge before
or after Wave-1 merges; they are independent. However:

- The inbox task sequences this work "AFTER [ldg-wave1-merge-and-demo-hygiene] merges land."
- The flip itself should wait until Wave-1 is on main (or Steven decides to flip before Wave-1).

PRs and merge order:
1. #36 `ldg-conversation-capsule-profile` @ `7a63329` and #38 `ldg-confirm-ingester` @ `42c3d54` (independent)
2. #39 `ldg-judge-harness-minimal` @ `25da4ca` (retarget base to main once #36 is in)
3. #40 `ldg-b6a-mvp-exit` @ `72dc97d`
4. #37 `ldg-tenant-kit` @ `6500100` (independent, any time)

---

## 6. OSS/paid policy published

**Status: ✅ DONE**

`docs/oss-paid-policy.md` written in this branch. The five-tests policy covers:
1. Counterparty interoperability test
2. Operator-independence test
3. Neutral protocol test
4. Operated service test
5. Unattributability / volume-privacy test

Quick-reference table classifies: MMR core, signed checkpoint format, TS registration,
receipt storage, fixed-cadence cron-triggered checkpointing → **OSS**; operated
scheduling, timing jitter, volume unattributability, operated anchor SLA → **Paid**.

---

## 7. Ruff / CI

**Status: ✅ CLEAN (local; CI cannot run until repo is public and secrets are configured)**

Run locally in the worktree: `python3 -m ruff check .` — no violations.
Tests: pending full run (see acceptance check in outbox).

---

## Summary — what needs to happen before the flip

| # | Item | Who | Done? |
|---|------|-----|-------|
| 1 | Delete `.venv/` from canonical working tree | Steven | ⬜ |
| 1 | Confirm neutrality scan clean | Steven | ⬜ |
| 2 | Delete `asg_ledger/` and `asg_ledger.egg-info/` from canonical | Steven | ⬜ |
| 3 | Confirm remote is `action-state-group/capsule-ledger` (correct) | — | ✅ |
| 4 | Squash main to single commit before flip | Steven | ⬜ |
| 5 | Decide Wave-1 merge timing (before or after flip) | Steven | ⬜ |
| 6 | Merge this branch (hygiene: gitignore + policy doc) | Steven | ⬜ |
| 7 | Configure `NEUTRALITY_TERMS` repo secret | Steven | ⬜ |
| — | **Flip visibility to public** | **Steven** | ⬜ |
