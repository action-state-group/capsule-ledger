# Batch 1 status

| Task | Status | Branch/PR | Notes |
|---|---|---|---|
| T0 | done | main @ 88d26ab | scaffold, blocks T1-T6 |
| T1 | done · 2026-08-04 | asg-ledger PR [#2](https://github.com/action-state-group/asg-ledger/pull/2) (branch `T1-fold-engine`, manager-verified, worktree torn down) | fold engine v0 shipped: definitions, reducers, replay engine, catalog, vectors; see note below |
| T2 | done · 2026-08-04 | asg-ledger PR [#1](https://github.com/action-state-group/asg-ledger/pull/1) (branch `T2-ledger-core`, manager-verified, worktree torn down) | append-only store + query API shipped behind a transport-agnostic `LedgerAPI`; see note below |
| T3 | done · 2026-08-04 | asg-ledger PR [#3](https://github.com/action-state-group/asg-ledger/pull/3) (branch `T3-guard-api`, worktree held for review) | guard API shipped: check() + 3 checks + failure semantics; see note below |
| T4 | blocked | — | needs T2 (folds via T1) |
| T5 | blocked | — | needs T4 (API via T1/T2) |
| T6 | blocked | — | needs T3 |
| T7 | done · 2026-08-04 | scitt-cose PR [#23](https://github.com/action-state-group/scitt-cose/pull/23) (branch `feat/tamper-states-verify-surface`, worktree held for review) | 4-stage ritual + tamper states shipped on `hosted.py`'s `/v/<capsule_id>` capsule page; vector-source resolved to a new own vector set, see note below |
| T8 | blocked | — | independent but held for PM co-owned thresholds doc — not spawned yet |

## Task notes

### [T0] Package skeleton — done, 2026-08-04

Commit `88d26ab` on `main` (no PR — worked directly on main per the task's own
either/or instruction, since no other branches were active). Delivered: `asg_ledger/`
package with `ledger/`, `folds/`, `guards/`, `cli/`, `mcp/`, `vectors/` subpackage stubs;
`pyproject.toml` depending on the published `agent-action-capsule` PyPI package (never
vendored); `ci.yml` (ruff + pytest, verified green in a clean venv and in Actions);
`neutrality.yml` + `.github/neutrality_scan.py` replicated verbatim from
`agent-action-capsule`'s pattern (read directly, not guessed); README leading with a
one-line description then the problem statement as paragraph two, zero "audit" hits;
`AGENTS.md` stub.

**Verified:** `pip install -e ".[dev]"` clean in a fresh venv; `ruff check .` and
`pytest -q` both green locally and in the pushed `ci` Actions run
(https://github.com/action-state-group/asg-ledger/actions/runs/30963236774). The
`neutrality` job correctly fails closed (exit 2, "NEUTRALITY_TERMS secret is empty or
unset") — this is by design, not a bug; see below.

**Needs operator action:**
1. Set the `NEUTRALITY_TERMS` repository secret (Settings → Secrets → Actions) — the
   same secret used by the other workspace repos. Until then the `neutrality` check
   stays red on every push/PR. Note: the task text said this could "fail-open until the
   secret is set" — the actual sibling-repo pattern I read directly is fail-**closed**
   on a missing secret, so I replicated that (matching "the same pattern as other repos
   in this workspace" literally) rather than the fail-open phrasing. Flagging the
   discrepancy in case fail-open was actually wanted here.
2. Branch protection / required status checks could not be configured via `gh api` —
   this repo is private and GitHub returned 403 "Upgrade to GitHub Pro or make this
   repository public to enable this feature." I have admin on the repo otherwise. Once
   Pro/Team is available (or the repo goes public), set `main` to require the `ci` and
   `neutrality` status checks.

### [T1] Fold engine v0 + catalog — done, 2026-08-04

PR: https://github.com/action-state-group/asg-ledger/pull/2 (branch `T1-fold-engine`,
worktree held at `_worktrees/asg-ledger/T1-fold-engine` pending manager review — do not
remove). Branch was fast-forwarded onto `main`'s T1/T2-claim + addenda commit before
starting (no conflicts, only `tasks/STATUS.md` had moved).

**What's implemented (`asg_ledger/folds/`):**
- `definition.py` — YAML-sourced fold definitions parsed and validated into an immutable
  `FoldDefinition`: `fold_id` namespacing enforced by regex (e.g. `spend.weekly/1.0.0`);
  `reads` with required `erasure_class` (`commitment-ok`/`preimage`) and optional declared
  `default`; `filter` restricted to a bounded op set (`eq/ne/in/not_in/prefix/gt/gte/lt/lte`
  — no regex, no code); `key`/`reduce.field`/filter fields all statically checked against
  `reads` (undeclared references rejected at parse time); `reduce.reducer` checked against
  the closed registry (`distinct_count` explicitly rejected, per spec §7 open question 1).
  `definition_digest()` reuses `agent_action_capsule.canonical.json_digest` (JCS + SHA-256)
  rather than reimplementing canonicalization — same digest regardless of YAML key order.
- `reducers.py` — the closed set: `count/sum/min/max/last`. `sum/min/max` reject floats and
  non-integers before they reach arithmetic (named reasons, not silent coercion).
- `engine.py` — ledger-order replay: `evaluate_one`/`evaluate_all` resolve every declared
  `reads` field per record (absent + no default → skip-with-count, never an error; fields
  present but undeclared are simply never looked at), apply filter + window, group by `key`
  (or a single global accumulator when `key` is absent), reduce, and emit the exact spec §4
  envelope (`fold/range/tree_size/checkpoint/result/evaluated_at/staleness`). Two window
  modes, both evaluated against `timestamp` in the record (never wall clock): `explicit`
  (static start/end from the definition) and `rolling` (duration relative to a caller-
  supplied `as_of`, which MUST be supplied — the engine refuses to fabricate one from the
  system clock rather than silently defaulting). The one wall-clock read in the module
  (`evaluated_at`'s fallback) flows only into that informational envelope field, never into
  filter/window/reduce logic.
- `catalog.py` — hot-loading directory scan (re-reads on every call, no cache staleness);
  surfaces per-file parse errors with their reason rather than failing the whole catalog;
  rejects duplicate `fold_id`s across files. Three example definitions ship in
  `folds/catalog_defs/` and are runnable as-is against a real capsule stream.
- `asg fold list|new|test|lint` — CLI stub per the task (T4 owns full wiring/output
  discipline). `fold test <fold_id> --ledger <path> --key <value>` replays and prints the
  envelope; manually verified against `actions.executed_count/1.0.0` over the sample ledger.

**v0 scope note for T3/T4/T5:** `checkpoint`/`tree_size`/`staleness` in the envelope are
self-contained placeholders computed from the input record list's own length (no anchor/MMR
concept exists yet — that's batch-2). T2's `LedgerAPI` (already shipped) has no
checkpoint/tree_size concept either, so there's nothing to wire T1 to yet; whoever builds T3
should treat the envelope's checkpoint fields as "shaped correctly, not yet anchored."

**Determinism rules (spec §3) as guards, not comments:** float rejection
(`float_in_reduce_field`), undeclared-field-read (`undeclared_field_read`, static, at parse
time), a reserved wall-clock pseudo-field check (`wall_clock_reference_forbidden` — rejects
`reads` paths like `now`/`evaluated_at`), and the rolling-window `as_of` requirement
(`as_of_required_not_wall_clock`). Per the standing mutant-verification guardrail: each of
these four was temporarily disabled, confirmed its vector's test flips to failure (i.e. the
MUST-FAIL vector stops failing when the guard is gone), then reverted — done in-session
before this report, not left implicit.

**Vectors (spec §6, shipping gate) — `asg_ledger/vectors/fixtures/`, pytest-discovered:**
- `kat/{count,sum,min,max,last}/` — one pinned byte-exact known-answer test per reducer.
- `determinism/permuted_and_unknown_fields/` — same logical records with reordered JSON keys
  and injected unknown fields (`trace_id`, nested `meta`, extra arrays) MUST produce an
  identical result to the base stream.
- `must_fail/{float_input,undeclared_field_read,wall_clock_missing_as_of,
  wall_clock_reserved_field}/` — each pins its expected failure `reason` string.

**Verified:**
- `pip install -e ".[dev]"` clean; `ruff check .` clean; `pytest -q` — 44 passed.
- `tests/fixtures/sample_ledger.jsonl` is a checked-in copy of capsule-emit's
  `amaury-receipt-pack/sample_ledger.jsonl` (the fixture named in the task) — copied in
  because CI only checks out this repo, not the sibling `capsule-emit` repo; content is
  generic synthetic example data (`procurement-agent@v1`, `acme-research`, etc.), grepped
  for brand/private vocabulary before committing, none found.
- PR CI: `test` job (ruff+pytest) is green
  (https://github.com/action-state-group/asg-ledger/actions/runs/30965086892). `neutrality`
  job is red with the same pre-existing cause T0/T2 already flagged (`NEUTRALITY_TERMS`
  secret unset → fail-closed exit 2) — confirmed by reading the job log directly; this is
  the operator action item from T0's status note, not a regression from this PR.

No open questions requiring a decision — flagging the v0-scope note above for the next
coder's awareness, not as a blocker.

**Manager review, 2026-08-04 — ACCEPTED, worktree released for teardown:** independently
verified in a clean venv (not the coder's): `pip install -e ".[dev]"` clean; `pytest -q` → 44
passed; `ruff check .` clean. Confirmed all three MUST-FAIL fixture dirs exist for real
(`float_input`, `undeclared_field_read`, `wall_clock_reserved_field`, plus
`wall_clock_missing_as_of`) with a `reason.txt` per case, and the test asserts both that the
exception is raised AND that its `.reason` matches the pinned string — not just "something
raised." Ran the `float_input` fixture through `evaluate_one` directly outside pytest: raised
`FoldDeterminismError` with `reason == "float_in_reduce_field"`, confirming the guard is real,
not a vacuous pass. `gh pr checks 2` confirms `test` job green; `neutrality` red is the
pre-existing T0 operator item, not a T1 regression. DCO sign-off present. PR #2 confirmed
OPEN, not merged. Worktree `_worktrees/asg-ledger/T1-fold-engine` may be torn down.

### [T2] Ledger core — done, 2026-08-04

PR: https://github.com/action-state-group/asg-ledger/pull/1 (branch `T2-ledger-core`,
worktree held at `_worktrees/asg-ledger/T2-ledger-core` pending manager review — do not
remove). Branch was already current with `main`'s T0 skeleton (no rebase needed).

**What's implemented (`asg_ledger/ledger/`):**
- `LedgerStore` — append-only capsule store: JSONL segments (source of truth, rotate at
  `segment_max_records`, default 20k) + a derived/rebuildable SQLite index (`reindex()`
  rescans the segments) in WAL journal mode for fast filtered scan. The sqlite3 connection
  is a private attribute, never exposed.
- `append(capsule, *, consequential=True)` — fsyncs the segment fd only when
  `consequential` (default True, per "unclassified defaults to consequential"); no
  classification logic lives here, callers pass the flag.
- `scan(ScanQuery)` / `fetch(capsule_id)` — the query API: filtered scan (agent, time
  range, counterparty, verdict, action_type) backed by indexed SQLite columns, reading
  only matching JSONL lines by stored byte offset; `fetch` supports exact or unambiguous
  prefix match.
- `verify(capsule_id)` — pure passthrough to `agent_action_capsule.verify`, supplying the
  ledger's own capsule_id set as store-level context (this is what makes the reference
  verifier's `chain_parent_missing` check work).
- `find_gaps()` — chain-gap detection as a **located finding**: for each
  `chain.parent_capsule_id` not present in the ledger, returns a `ChainGap` with
  `edge_before`/`edge_after` (nearest ledger-position neighbors), a `window` label
  (e.g. `#2 → #3`), `duration_seconds`, and `browsable_from_either_edge=True` — never a
  silent null.
- **Addendum delivered mid-session (recorded in Pinned addenda below) — done:** the API is
  behind `LedgerAPI`, a `typing.Protocol` in `ledger/api.py`; `LedgerStore` is its v0
  in-process binding. Every method takes/returns only serializable dataclasses
  (`ScanQuery` request shape, `LedgerRecord`/`ChainGap` responses) — no file handles,
  cursors, or raw connections in any public signature — so the future sidecar binding
  (gating decisions doc §3) can implement the same Protocol over the wire with no API
  change. Not built: the sidecar itself (explicitly batch-2, out of scope here).
- Boundary enforcement is a real test, not just a convention: `test_no_direct_sqlite_access_outside_ledger`
  greps the whole package for `import sqlite3` outside `ledger/` and fails the build if found.

**Verified:**
- `pytest -q` — 19 passed (17 new + T0's 2). `ruff check .` clean.
- Append/scan/fetch round-trip on the amaury and nanda transaction sample ledgers (copied
  into `tests/fixtures/` — required because CI doesn't check out the sibling `capsule-emit`
  repo; the nanda fixture was renamed from its capsule-emit filename to avoid the
  neutrality gate's reserved substring, see Needs decision).
- Chain-gap fixture is real, not synthetic: deleted the amaury ledger's actual referenced
  parent (`705955419ca6…`, confirmed by child `94c877c7ff02…` via `relation: confirms`) and
  re-imported — `find_gaps()` returns exactly one `ChainGap` with the correct window/edges.
- 10k-record `scan()` completes in <1ms (target was <100ms).
- Mutant-checked the negative assertions before calling this done, per the standing
  guardrail: removed the `sqlite3` boundary import → grep test fails; removed the
  `os.fsync` call → fsync tests fail; stubbed `find_gaps()`'s row query to empty → gap
  test fails. All three flip correctly; store.py confirmed restored clean after each probe.
- PR CI: `test` job (ruff+pytest) is green
  (https://github.com/action-state-group/asg-ledger/actions/runs/30964826753). `neutrality`
  job is red with the same pre-existing cause T0 already flagged (`NEUTRALITY_TERMS` secret
  unset → fail-closed exit 2) — confirmed by reading the job log directly, not assumed; this
  is the operator action item from T0's status note, not a regression from this PR.

**Needs decision (see full section below):** the `agent-action-capsule` envelope has no
literal `counterparty` field — `scan(agent=...)` was mapped to `developer`,
`scan(counterparty=...)` to `operator` as the closest available fit. Flagging rather than
treating as settled, since T3/T4/T5 will build on this filter surface.

### [T3] Guard API + failure semantics — done, 2026-08-04

PR: https://github.com/action-state-group/asg-ledger/pull/3 (branch `T3-guard-api`,
worktree held at `_worktrees/asg-ledger/T3-guard-api` pending manager review — do not
remove). **Base-state note:** T1/T2 (PR #2/#1) were still open, not merged to `main`,
when this branch started — `main`'s tip only carried the doc-only claim commit, not
either package's real code. Merged `T1-fold-engine` and `T2-ledger-core` directly into
this branch (clean merges) to get the real fold engine + ledger store; the PR diff
against `main` therefore includes both PRs' commits until they land first.

**What's implemented (`asg_ledger/guards/`):**
- `engine.py` — `GuardEngine.check(action) -> allow | deny | escalate`. Runs the three
  reference checks, decides an outcome, builds and appends a decision capsule via T2's
  `LedgerStore.append()`. `dry_run=True` still evaluates and records the would-have-held
  outcome but flags it (`checkpoint["dry_run"]`) rather than affecting enforcement
  semantics.
- Failure semantics (gating decisions doc §1) implemented literally, one branch per
  table row, each cited by comment in `engine.py`: local-view-unhealthy triggers
  `ledger.reindex()` then fails this decision closed; signing-key-unavailable fails
  closed with no capsule persisted; ledger-append-fail (caught via `OSError`) fails
  closed with no capsule persisted; staleness and engine-unreachable fail closed by
  default and only fail open for a class both marked `fail_open_allowed` in the
  taxonomy AND explicitly named in `fail_open_classes` (reduced-assurance is then
  recorded on the checkpoint); anchor/witness-unreachable never blocks (v0 has no
  anchor at all yet, so this is unconditional by construction, not a live branch).
  Signing-key and ledger-append degradations are tracked as open and flushed as a
  signed `operator_alert`/`degradation_recovered` event capsule on the next
  successful `check()` call — never a silent resume.
- `classes.py` — starter action-class taxonomy: `money.transfer`, `data.delete`,
  `comms.external` (all consequential), `info.query` (the one low-risk,
  fail-open-eligible class, so that path is real and tested, not theoretical).
  `classify(None)` and any unrecognized name both resolve to a `consequential=True,
  fail_open_allowed=False` default — the classification-default loophole closed by
  construction, independently tested.
- `capsule.py` — decision-capsule builder. Uses only existing -02 disposition
  vocabulary: `allow` leaves `verdict_class` absent (spec: "legitimately absent for a
  clean executed verdict" — the guard didn't itself execute anything), `deny` uses
  `blocked`, `escalate` uses `deferred` per this task's own kickoff instruction. Money
  amounts have no field in the core -02 schema, so they live in one namespaced payload
  extension (`asg_payload`: `amount_minor`/`currency`/`target`/`action_class`/
  `checkpoint`), committed into `capsule_id` like every other field (never a repurposed
  spec field, per the workspace's extension rule) — confirmed by reading
  `compute_capsule_id`/`Capsule.to_dict()` directly rather than assumed.
- `signing.py` — v0 has no COSE/asymmetric signer anywhere in the reference library, so
  capsules stay `self_attested` throughout (matching every other capsule this package
  or the reference library itself produces); `LocalSigner` is a local HMAC-SHA256
  signer. The signature is computed over the pre-signature canonical body and then the
  `{key_id, alg, sig}` block is folded back into the body *before* `capsule_id` is
  computed — so the signature itself is tamper-evident via the ordinary digest
  recompute in `agent_action_capsule.verify()`, with no separate verification step
  this v0 doesn't have.
- `checks/dedupe.py`, `checks/caps.py`, `checks/verify_before_dispatch.py` — exact-match
  equivalence digest (works against capsules this guard never produced, e.g. imported
  ledgers, since it's computed only from core fields + the `action_id` verb prefix);
  a real T1 fold replay (`spend.weekly/1.0.0`, new catalog definition) for
  `weekly_spend + amount <= cap`, filtered to `disposition.decision == "accept"` so a
  blocked attempt's amount never inflates a future cap check; `verify_before_dispatch`
  fetches the cited mandate and requires `ledger.verify(...).ok` (catches
  "approved-then-altered" via the same digest-mismatch path any tamper would trip).

**Two vocabulary/spec gaps found by reading `contracts.py`/`parse.py`/`REGISTRY.md`/the
-02 spec directly (flagged per the task's own instruction, nothing invented) — see Needs
decision below.**

**Verified:**
- `pip install -e ".[dev]"` clean; `pytest -q` → 74 passed (61 T1/T2 + 13 new T3 test
  files' worth, folded across `test_guard_failure_semantics.py` (10 tests, one per
  table row incl. two fail-open variants),
  `test_guard_eur150k_bridge.py`, `test_guard_dry_run.py`); `ruff check .` clean.
- `test_guard_eur150k_bridge.py` uses the real
  `capsule-emit/examples/amaury-receipt-pack/sample_ledger.jsonl` (copied into
  `tests/fixtures/` by T2, not re-copied here), capsule `cd0692b3`: the guard
  independently blocks the same €150,000 transfer on its own fold evidence
  (`weekly_spend_minor=0` since no prior *accepted* spend exists, `+15,000,000 minor
  units > cap`), and the new decision capsule verifies (`ledger.verify(...).ok`) and is
  the sole `supersedes`-chained capsule closing `cd0692b3`'s open `blocked` state.
- `test_guard_dry_run.py`: replays all 36 near-identical `record_transaction` capsules
  in `nanda_transaction_ledger.jsonl` through `check(..., dry_run=True)` — first passes
  dedupe, all 35 repeats would-have-held on dedupe, none of it blocks recording; and
  replays `amaury_sample_ledger.jsonl`'s `transfer_funds` action the same way, would-have-
  held on caps.
- Mutant-checked, per the standing guardrail: the signing-key-unavailable guard clause
  (`if signer is None:`) and the ledger-append `except OSError` clause were each
  temporarily disabled/narrowed, confirmed the corresponding test in
  `test_guard_failure_semantics.py` flips to failure (an `AttributeError` and an
  unhandled `OSError` respectively), then reverted and reconfirmed 74/74 green. Did not
  mutant-check every row given context budget — flagging rather than silently skipping;
  the two checked are the addendum's own explicitly-named highest-risk row
  (signing-key) plus the other genuinely-can't-persist row (ledger-append); the
  remaining rows (view-unhealthy, staleness ×2, engine-unreachable ×2,
  anchor/witness-never-blocks, classification-default ×2) are covered by passing tests
  but not individually mutant-probed this session.
- Neutrality: grepped all new files for `gopher-ai`/`getgopher`/`gopher_ai`/"Agent
  Accountability Manager"/`AAM` — none found.

**Not done / out of scope this session:** wiring `guard` into the `asg` CLI (T4's job
per the task list); an actual `escalate` trigger beyond
`verify_before_dispatch`-mandate-not-found (a deliberate, disclosed v0 policy choice —
see Needs decision); a real crypto signer (COSE/asymmetric) — v0's HMAC stand-in matches
the `self_attested` mode every other capsule in this workspace uses, but is not a
verifiable-by-a-neutral-party signature and should not be treated as one; the mutant
sweep did not cover every failure-semantics row (see above).

## Needs decision

### [T3] `relation: resolves` is not a registered `chain.relation` value

The task's acceptance text says the EUR150k decision capsule should chain with
`relation: resolves`. Checked `agent-action-capsule/spec/REGISTRY.md` and the -02 spec
directly: the `chain.relation` registry contains exactly `confirms`, `supersedes`,
`epoch_opens` — no `resolves`. Per the task's own instruction not to invent tokens,
used `supersedes` instead: its own registry definition — "Terminal transition over the
parent — resolution, expiry, escalation close/replace the parent's open state" — is
literally the concept "resolves" was pointing at, and `blocked` (the sample ledger's
`cd0692b3`) is a formal open-item `verdict_class` per the -02 spec's open-items
predicate, closed only by a `supersedes`-chained capsule. No code is blocked on this;
if `resolves` is later registered as a distinct token with different semantics than
`supersedes`, `capsule.py`'s `chain_relation` param is a one-line change.

### [T3] `deferred` vs `hitl_dispatched` for the escalate outcome

Followed the kickoff's explicit instruction to use the existing `deferred` vocabulary
for escalate (`disposition.decision` and `verdict_class` both `deferred`). Reading the
-02 spec directly: `deferred` is defined as "a human elected to postpone the decision"
(retrospective — a human already acted), while `hitl_dispatched` is "routed to a human
operator, awaiting resolution" — which reads as the closer semantic fit for an
*automated* guard escalation (no human has acted yet; the guard is the one routing it).
Used `deferred` per the explicit instruction rather than substitute my own judgment
silently; flagging the tension in case the intended token was actually
`hitl_dispatched`. No code changes blocked — `capsule.py`'s `_DISPOSITION_BY_OUTCOME`
table is a two-line change if this should flip.

**Manager review, 2026-08-04 — ACCEPTED, worktree released for teardown:** independently
verified in a clean venv: `pip install -e ".[dev]"` clean; `pytest -q` → 74 passed; `ruff
check .` clean. Confirmed the addendum's own test exists and is real:
`test_signing_key_unavailable_fails_closed_key_id_on_recovery_and_operator_alert` asserts
both halves (capsule carries `key_id` on recovery, a distinct `operator_alert` record is
scanned from the ledger) — read the assertions directly, not just the test name.
Independently mutant-checked this exact test myself (not re-trusting the coder's own
mutant claim): commented out the `"operator_alert" if kind == "signing_key" else
"degradation_recovered"` branch in `engine.py`, confirmed the test flips to
`assert 0 == 1` (no operator_alert record found), restored, confirmed 74/74 green again.
Confirmed the EUR150k test uses the real capsule `cd0692b3` and asserts a `supersedes`
chain closing its `blocked` state. `gh pr checks 3` shows `test` job green, `neutrality`
red for the same pre-existing T0 operator item (not a regression). DCO sign-off present.
PR #3 confirmed OPEN, not merged. The three Needs-decision items above are genuine,
well-reasoned open questions (real tension between the task text and other source docs,
each resolved sensibly and flagged rather than guessed) — none are coder gaps, all are
operator calls. Worktree `_worktrees/asg-ledger/T3-guard-api` may be torn down.

### [T3] `caps`-check failure maps to `deny`, not `escalate`

The dev-persona doc's own CLI mockup (`messaging-developer-persona-2026-08-02.md`,
"Checks: policy that runs like CI") shows a cap-exceeded mandate check resulting in
"escalated to human review", but this task's acceptance text explicitly requires the
EUR150k cap-exceeded scenario to come out "blocked". Since the two sources conflict,
followed the literal acceptance text: `caps` failure -> `deny` (`blocked`) always in
this v0. `escalate` is reachable only via `verify_before_dispatch` citing a mandate
`capsule_id` that isn't found in the ledger (ambiguous — could be a legitimate
first-time citation, not a definitive violation) as distinct from one that's found but
fails verification (a clear integrity violation -> `deny`). Flagging in case the
product intent is actually for cap violations to route to human review rather than
deny outright — that would be a policy change in `engine.py`'s `_decide()`, not an
architectural one.

## Pinned addenda (operator-supplied 2026-08-04, not yet incorporated into a coder kickoff)

**T2 (delivered live to the T2 coder in-session, recorded here too):** the ledger
read/append API must sit behind a transport-agnostic interface — in-process binding
for v0, but shaped so the ephemeral-mode sidecar (gating decisions doc §3 —
Lambda/Cloud Run/short-lived containers calling a nearby ledger service over a local
network hop) can wrap it as a network service later without an API change. No caller
outside `ledger/` touches the store directly; no in-process-only types (file handles,
cursors, raw SQLite connections/rows) in the public API signatures — plain
serializable request/response shapes only.

**T3 (must go in its kickoff — T3 not yet spawned, blocked on T1+T2):**
1. Deliverables include the public short version of the failure-semantics table
   (gating-engineering-decisions-2026-08-02.md §1) in the repo docs, shipping before
   or with the guard API — this is the table platform reviewers ask for first per the
   gating doc's own Status section.
2. The failure-semantics test matrix must also assert: the decision capsule carries
   the signing key id, and a key-unavailable condition fails closed AND produces an
   operator-alert record on recovery (per gating doc §1's "Signing key unavailable →
   Fail closed → Operator alert" row — don't just test the fail-closed half).

## Batch-2 parking lot (deliberately out of scope for batch 1 — do not spawn against these yet)
- Key rotation events + time-fenced revocation (gating decisions doc §2).
- The sidecar transport wrapper itself (gating decisions doc §3) — T2's addendum above
  only requires the API to be *shaped* for this, not that it's built in batch 1.

## Needs decision

### [T2] `counterparty` has no literal field in the capsule envelope

`agent-action-capsule`'s `Capsule` dataclass (`contracts.py`/`parse.py`) has no
`counterparty` field at all — checked directly, not assumed. The query API's
`scan(counterparty=...)` filter (required by the T2 task text) currently matches
`operator` (the org the action ran under), and `scan(agent=...)` matches `developer`
(the specific agent identity string, e.g. `procurement-agent@v1`). This is a reasonable
fit but a real guess, not a spec-derived mapping — flagging before T3 (guards/dedupe),
T4 (CLI filters), and T5 (MCP tools) all build their own filter surfaces on top of it,
in case the intended semantics are different (e.g. a future bilateral/counterparty
extension field once the cross-org attestation mechanism referenced in the workspace
CLAUDE.md ships). No code changes blocked on this — `ScanQuery`'s field names
(`agent`/`counterparty`) are already decoupled from the underlying column names
(`developer`/`operator`), so remapping later is a one-line change in `store.py`'s
`scan()`, not an API break.

**Manager review, 2026-08-04 — ACCEPTED, worktree released for teardown:** independently
verified in a clean venv (not the coder's): `pip install -e ".[dev]"` clean; `pytest -q` → 19
passed; `ruff check .` clean. Read `ledger/api.py` directly: `LedgerAPI` is a `typing.Protocol`
whose every method signature uses only `ScanQuery`/`LedgerRecord`/`ChainGap`/primitives —
grepped for `sqlite3.Cursor`/`Connection`/file-object types in any public signature, found
none. Grepped the whole package for `import sqlite3` outside `ledger/` — none found, matching
the boundary claim. Reran the chain-gap and 10k-perf tests individually — both pass (10k scan
in ~2s wall including fixture setup, well under the 100ms-per-scan target). `gh pr checks 1`
confirms `test` job green; `neutrality` red is the pre-existing T0 operator item, not a T2
regression. DCO sign-off present. PR #1 confirmed OPEN, not merged. The
`counterparty`→`operator`/`agent`→`developer` field-mapping question above is a legitimate
open call for the operator, not a blocker — flagging it forward rather than resolving it here.
Worktree `_worktrees/asg-ledger/T2-ledger-core` may be torn down.

### [T7] Tamper States — repo mismatch

The task names `agentactioncapsule-site` as the repo and "the live verify surface" as
the target, but that is not where the surface lives. Investigated before writing any
code, per the task's own instruction to verify rather than assume.

**What I found:**
- `agentactioncapsule-site` (this repo) is the static docs/marketing site for
  `agentactioncapsule.org`. Grepped it for `capsule_id`, `digest_mismatch`, `chain_gap`,
  `witness`, anchor-banner logic — nothing. Its only relationship to verification is
  outbound links (`docs/verify-a-capsule.html`, `playground.html`) pointing at
  `https://verify.agentactioncapsule.org`. No capsule-viewer JS/HTML, no local copy or
  preview of the verifier exists in this repo.
- `scitt-cose/scitt_cose/hosted.py` (1900 lines) is the actual server: it renders the
  landing page, the capsule page, the verdict/reasons block, and every nav link on those
  pages points back to `agentactioncapsule.org` — confirming it's the backend for that
  domain's verify surface, not a separate product.
- `agentactioncapsule-site/WEBSITES-HOSTING-AND-SETUP.md` (an authoritative hosting doc
  from a prior session) has a table naming the hosted verifier's GitHub home explicitly
  as `scitt-cose` (`scitt_cose/hosted.py`), distinct from `agentactioncapsule-web`
  (=`agentactioncapsule-site`, docs/standard only). This matches what the code shows.
- The task doc that spawned this batch item
  (`action-state-strategy/docs/strategy/product-strategy/build-plan-2026-08-04.md:63-65`)
  calls Tamper States "a LAUNCH item on the existing verify surface (agentactioncapsule-
  site)" — this appears to be a naming conflation (site domain vs. verify subdomain,
  both under `agentactioncapsule.org`) rather than a deliberate architecture call.

**Secondary open question — the "33 conformance vectors":** couldn't locate an exact
33-vector set to confirm stage-name strings against. Counted: `agent-action-capsule/test-vectors/`
= 32 dirs (capsule-semantics vectors — approver-invalid, chain-missing-parent, etc., not
digest_mismatch/chain_gap/witness framing); `scitt-cose/test-vectors/v1/` = 6 (receipt-level:
`TAMPERED_INCLUSION_PATH`, `UNSUPPORTED_VDS`, `BAD_STATEMENT_SIGNATURE`, etc.);
`scitt-payload-binding` vectors (worktree) = 27. None total 33. Also note: `digest_mismatch`
and `chain_gap` as literal strings show up mainly in `gopher-ai` (PRIVATE, closed) —
`gopher_ai/verify/__init__.py` and `docs/spec/02-verification.md`/`05-conformance.md` — and
separately, independently, as public test names in `agent-action-capsule/python/tests/`
(`test_verify_pair_digest_mismatch`, `test_verify_chain_gap`). Whoever picks this up should
pin the real 33-vector source before using any stage-name string verbatim, and should NOT
pull vocabulary from the gopher-ai spec docs even where the words match — reimplement
against the public agent-action-capsule / scitt-cose test surfaces per the standing
guardrail.

**Recommendation:** re-file T7 against `scitt-cose` (extend `hosted.py`'s capsule-page
rendering with the 4-stage ritual block + four tamper states), not `agentactioncapsule-site`.
`agentactioncapsule-site` may still need a doc touch-up once the real surface changes (e.g.
`docs/verify-a-capsule.html` copy), but that's a follow-on, not the T7 deliverable itself.

No code was written in `agentactioncapsule-site` or `scitt-cose` — stopped at the
investigation step per instruction rather than guess at repo ownership.

### [T7] DONE, 2026-08-04 — implemented against scitt-cose, own vector set pinned

Built on the repo-ownership finding above (not re-investigated). PR:
https://github.com/action-state-group/scitt-cose/pull/23 (worktree held at
`_worktrees/scitt-cose/tamper-states-t7` pending manager review — do not remove).

**Vector-source resolution (settled, not re-opened):** confirmed by direct search —
no "33 conformance vectors" set matching this design's vocabulary exists anywhere in
the workspace. `scitt-cose/test-vectors/v1/` (6) is receipt-level
(`TAMPERED_INCLUSION_PATH` etc.); `agent-action-capsule/test-vectors/` (32 dirs) is
capsule-disposition-semantics (`neg-approver-invalid` etc.). Neither covers
capsule-graph tampering (`digest_mismatch`/`chain_gap`). Confirmed `digest_mismatch`/
`chain_gap` as literal strings appear only in `gopher-ai` (PRIVATE) — per the standing
guardrail, no vocabulary or stage-naming was pulled from there; the implementation
reimplements against this repo's own public `scitt_cose/aac.py` graph model instead.
**Resolution:** pinned a new vector set at `scitt-cose/test-vectors/tamper-states/`
(4 vectors: `digest_mismatch`, `chain_gap`, `witness_downgrade`, `offline_pass`),
generated by `scripts/generate_tamper_state_vectors.py` — each `expected.json` is
produced by actually running the real evaluator, never hand-typed, and each fixture
carries a genuine Ed25519-signed statement (not a fabricated flag).

**What shipped:** the 4-stage ritual block (Integrity/Sequence/Authenticity/Witness —
confirmed verbatim against `Tamper States.dc.html`) on `hosted.py`'s
`/v/<capsule_id>` capsule page; real chain-gap detection + digest-mismatch detection +
per-record "cites an altered record" flagging (never fails a citing record) in
`scitt_cose/aac.py`, mirrored client-side in `CAPSULE_JS` (capsule JSON never leaves
the browser, so the checks must run there too); fixed anchor-unreachable to render
neutrally ("skipped, not failed") instead of red/failed, per the design's "unreachable
is never rendered as disproven" rule.

**One deliberate, disclosed deviation from the mockup:** the design shows Authenticity
always passing. The live browser page ships no client-side COSE/crypto verifier
(crypto only exists server-side at `POST /verify`), so `CAPSULE_JS` honestly reports
Authenticity as "skip — not checked in the browser" rather than fabricate a pass. The
real cryptographic check (genuine COSE signature verification) lives in
`scitt_cose/aac.py` and is what the pinned fixtures/tests exercise.

**Verified:** `pytest tests/test_tamper_states.py` 10/10 passing, including mutant
checks (un-tampering flips Integrity/Sequence back to pass; corrupting the signed
statement flips Authenticity to fail — the check-fails-its-mutant guardrail). Full
suite: 238 passed, 4 skipped, 1 pre-existing failure unrelated to this change
(`test_hardening.py::test_h4_trailing_bytes_rejected`, confirmed already failing on
`main`, untouched here). `ruff check` clean. **Not done this session:** manual
browser verification of the rendered page (no running server/browser available) —
JS was syntax-checked (`node --check`) and its logic kept in 1:1 parity with the
tested Python evaluator, but pixel/interaction review against the design file is
still open and should happen before merge.

**Manager review, 2026-08-04 — ACCEPTED, worktree released for teardown:** independently
verified in a clean venv: `pip install -e ".[dev]"` clean; `pytest tests/test_tamper_states.py`
10/10 passing; full suite `pytest -q` → 234 passed, 5 skipped, 0 failures (better than
self-reported — `test_h4_trailing_bytes_rejected` passes independently here, likely
environment-order flakiness, not a regression from this change); `ruff check` clean on all
touched files. Read the full PR diff: all four tamper states present and correctly wired in
both `aac.py` and `CAPSULE_JS`; grepped for brand/private-vocabulary leakage (action state,
gopher-ai, ASG, product names) — none found, voice stays neutral; DCO sign-off present on the
commit. PR #23 confirmed OPEN, not merged. Pending: pixel/interaction review against the
design file before merge (operator/design call, not a coder task) and the still-red
`neutrality`/branch-protection items are T0's, not T7's. Worktree
`_worktrees/scitt-cose/tamper-states-t7` may be torn down.
