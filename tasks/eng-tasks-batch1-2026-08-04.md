# Eng tasks — batch 1 (spawn-ready), 2026-08-04
**PRIVATE. Each task below is written to be handed to a spawned coding agent verbatim,
with one human-accountable review per PR. Dependency order matters: T0 → (T1 ∥ T2 ∥ T7)
→ T3 → (T4 ∥ T5 ∥ T6). T7 and T8 are independent and can start immediately.
Sources of truth every task must read first are listed per task; the shared ones are:
`fold-definition-format-spec-draft-2026-08-04.md`, `gating-engineering-decisions-2026-08-02.md`,
`decisions-and-launch-scope-v2-2026-08-02.md` (§14–15), and the design handoff README
(`docs/design/design_handoff_capsule_ledger_ux/README.md`).**

**Standing guardrails for every task:** no product brand or AAM/private vocabulary in
open repos (NEUTRALITY_TERMS is CI-fenced); the model never computes evidence — every
numeric output carries a fold envelope or names its record; refusals/blocks are records,
not errors; brick color/failure states only for verification failure; nothing from
`gopher-ai` (closed) is copied into open packages — reimplement against public interfaces.

---

## T0 — Scaffold the control-plane package (blocks T1–T6)
**Repo:** new, working name `asg-ledger` (private until trademark clears; structured for
rename). **Goal:** Python package skeleton: `ledger/` (append + read), `folds/`, `guards/`,
`cli/`, `mcp/`, `vectors/`; pyproject; ruff + pytest CI; README leading with the problem
("limits your agents cannot exceed, memory they cannot lie about" — format is paragraph
two); AGENTS.md stub. Capsule parsing via the public `agent-action-capsule` reference lib
as a dependency — never vendored.
**Acceptance:** `pip install -e .` clean; CI green on empty test suite; README passes the
no-compliance-vocabulary rule (no "audit"); NEUTRALITY_TERMS check wired.

## T1 — Fold engine v0 + catalog
**Spec:** the fold-definition draft, verbatim; decisions doc §15 for DX criteria.
**Goal:** definition parser (YAML → JCS → definition digest); reducers count/sum/min/max/
last (integer minor units only — floats are a MUST-FAIL); key/filter/window per spec;
result envelope `{fold, range, tree_size, checkpoint, result, evaluated_at, staleness}`;
replay evaluation over a capsule stream; namespacing enforced.
**CLI surface (in T4's frame, stub here):** `fold list`, `fold new`, `fold test`,
`fold lint`. Hot-load definitions from a configured directory.
**Acceptance:** per-reducer KATs with pinned streams → byte-exact results; determinism
mutants (permuted irrelevant fields, injected unknown fields) produce identical results;
MUST-FAIL vectors (float input, undeclared field read, wall-clock use) fail with named
reasons; `fold test` replays over a fixture ledger (use
`capsule-emit/examples/amaury-receipt-pack/sample_ledger.jsonl`) and prints the envelope.

## T2 — Ledger core: append-only store + query API
**Goal:** append-only ledger (JSONL segments + SQLite index is fine for v0) with chain
linkage (`parent_capsule_id`), gap detection surfaced as a *located finding* (window +
edges, per Tamper States design), and the query API: filtered scan (agent, time range,
counterparty, verdict, action_type) + record fetch + verify passthrough. WAL-style append
semantics; fsync on consequential classes.
**Reuse:** `capsule-emit`'s ledger-view CLI as prior art (read its code; port patterns,
not files). **Acceptance:** append/scan/fetch round-trip on the amaury + tax-audit sample
ledgers; chain-gap fixture renders the located window; 10k-record scan < 100ms; the
query API is the ONLY read path T1/T3–T6 use (no direct SQLite access outside `ledger/`).

## T3 — Guard API + three reference checks + dry_run (depends T1, T2)
**Spec:** gating doc §1 (failure semantics — implement the table literally, including
unclassified-defaults-to-consequential and the starter action-class taxonomy);
dev-persona doc for check semantics.
**Goal:** `check(action) → allow | deny | escalate` with every result carrying evaluated
constraints, fold envelopes read, checkpoint age; decision itself appended as a capsule
(disposition per -02 vocabulary — for the escalate path use the existing `deferred`
vocabulary; do NOT invent a `timeout` token: file the vocabulary question to the spec
notes instead). Checks: dedupe (equivalence lookup — exact-match index v0), caps (fold
predicate), verify_before_dispatch (cited mandate digest verifies). `dry_run` mode records
would-have-held outcomes without blocking.
**Acceptance:** the failure-semantics table as a test matrix (each row = a test: WAL
write failure → fail closed for consequential class, etc.); the €150k bridge scenario
reproduced end-to-end on the amaury ledger (blocked, fold evidence, decision capsule
chained `relation: resolves`); dry_run over the sample ledgers yields the 7 would-have-held
rows shaped like the Dry Run Report design's data.

## T4 — CLI: git verbs over the query API (depends T2; folds via T1)
**Goal:** `asg log / show / verify / bundle` + `asg fold list|new|test|lint` +
`asg constraints list` + `asg agents --status`. Output discipline: every aggregate prints
its envelope line (DM-Mono format from the handoff README backend-mapping section);
`log` supports the filter set and prints the CLI-echo canonical form; `bundle` produces a
self-contained verifiable slice + the verify-surface permalink (fragment-carried).
`diff/blame/bisect` are batch 2 — leave stubs with help text.
**Acceptance:** golden-output tests for each verb on the fixture ledgers; `bundle` output
verifies on the local verifier; `verify` exit codes suit CI use.

## T5 — Skill file + MCP advisory server (depends T4 for CLI; T1/T2 for API)
**Goal:** (a) `AGENTS.md`/skill teaching the CLI to shell-capable harnesses — documentation,
reviewed as Tier-1 copy. (b) MCP server (FastMCP, stdio) exposing: ledger.query, fold.get,
fold.list, budget.remaining, action.been_done, constraints.list, decision.explain,
record.get, record.verify, intent.declare (only write). All read tools return envelope-
carrying answers; tool descriptions are the catalog descriptions. Config: backend = local
path now; transport/auth abstraction stubbed for the remote (paid) case — same server,
different backend, per decisions doc §15. Use the mcp-builder patterns.
**Acceptance:** tool-schema snapshot test; a scripted Claude/Goose session (fixture) asks
"what did my agents do last night / budget left / why refused" and every answer carries
verification data; intent.declare round-trips to a capsule.

## T6 — Dry Run Report artifact generator (depends T3)
**Design:** `designs/Dry Run Report.dc.html` — recreate faithfully; the README's tokens
and product laws are acceptance criteria. **Goal:** `asg guard dry-run --since 7d --share`
emits a self-contained HTML report: headline folds with envelopes, per-guard tables with
record links, the ≈ tuning note frame (model call optional and clearly stubbed —
generator must work model-free with the note omitted), share chrome with the disclosure
line and fragment-carried payload (report data never server-side), "re-derives on open."
**Acceptance:** pixel-review against the design file; report from the fixture ledgers
matches the design's data shape; opening offline verifies; no network calls in the page.

## T7 — Tamper states on the live verify surface (independent — start now)
**Repo:** `agentactioncapsule-site`. **Design:** `designs/Tamper States.dc.html`.
**Goal:** implement the four states (digest_mismatch with named field group +
expected/recomputed digests; chain gap as located finding; witness downgrade "witnessed
1 of 3 · retrying — rung held"; offline pass with witness "skipped, not failed") + the
4-stage ritual block, using the 33 conformance vectors' stage names verbatim as the state
source. Citing records FLAG, never fail ("✓ verifies · cites an altered record").
**Guardrail:** this is the NEUTRAL surface — factual voice, no product brand, no marketing.
**Acceptance:** each negative vector class renders its correct state; visual-language-spec
compliance (brick only on failure, sage ⊘ for refusals); works with wifi off minus the
log check, and the page says so.

## T8 — Two-arm test packaging (independent — start now, PM co-owned)
**Goal:** Arm A = guards-only install (T3 subset packaged standalone, evidence machinery
present but silent); Arm B = full package with capsules/permalinks visible. Instrument:
install, first guard configured, enforcement on (vs dry_run), day-14 alive, evidence
features touched. Thresholds doc is written BEFORE distribution (decisions doc §0) —
agent drafts the instrumentation, Steven writes the thresholds.
**Acceptance:** both arms install in <10 min on a clean machine; telemetry is
opt-in-disclosed and aggregate-only (on-brand); a dry-run of the funnel report renders.

---

**Review cadence:** T0 same-day; T1/T2 are the deep reviews (the determinism rules and the
query-API boundary are the two places a bug becomes an architecture); T3's failure-matrix
tests reviewed line-by-line against the gating table; T4–T6 review = golden outputs +
product-law checklist; T7 against vectors; T8 against the pre-registered thresholds doc.
Batch 2 (after these land): diff/blame/bisect, Local Console + component library,
Onboarding flows, MMR + range proofs, proof-bundle service skeleton.