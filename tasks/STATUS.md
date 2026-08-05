# Batch 1 status

| Task | Status | Branch/PR | Notes |
|---|---|---|---|
| T0 | done | main @ 88d26ab | scaffold, blocks T1-T6 |
| T1 | blocked | — | needs T0 — unblocked now |
| T2 | blocked | — | needs T0 — unblocked now |
| T3 | blocked | — | needs T1 + T2 |
| T4 | blocked | — | needs T2 (folds via T1) |
| T5 | blocked | — | needs T4 (API via T1/T2) |
| T6 | blocked | — | needs T3 |
| T7 | re-filed vs. scitt-cose | — | manager confirmed the finding (hosted.py 1904 lines, hosting doc names scitt-cose as home of verify.actionstate.ai); re-spawned against the correct repo, see Needs decision for full evidence |
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

## Needs decision

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
