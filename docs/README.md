# capsule-ledger docs

Everything here is written to be read by a human dev **or** by a coding agent you point at it. No standards background needed.

## Start here

A guard checks each action your agent takes, appends the decision as a signed capsule to a local ledger — append-only signed records, no blockchain, no tokens, no consensus — and you can fold, bundle, and verify that ledger any time. That's the whole loop. Begin with the tutorials:

→ **Tutorials** — five-minute, copy-paste sessions, in order:
1. **[Your first ledger](tutorials/01-your-first-ledger.md)** — run a guard check, see the capsule land, read it back.
2. **[Reading what happened](tutorials/02-reading-what-happened.md)** — `capsule log` / `capsule show`, the git-log-style read path.
3. **[Folds and caps](tutorials/03-folds-and-caps.md)** — aggregate the ledger (spend caps, counts) without trusting a bare number.
4. **[Bundle and verify](tutorials/04-bundle-and-verify.md)** — hand someone a self-contained slice of the ledger they can verify offline, for free.

## Understand it

- **[Concepts in plain words](concepts.md)** — capsule, ledger, guard, verdict, fold, envelope, policy manifest, epoch, bundle — each one tied to a real field name or a real `capsule` command.
- **[Onboarding: hooking an agent up to capsule-ledger](onboarding.md)** — the four ways to wire an agent (or framework) into a running ledger; says plainly which paths aren't implemented yet.
- **[Guard failure semantics](failure-semantics.md)** — what happens when the ledger, the view, or the signer isn't available: what fails closed, what's allowed to fail open, and what always gets recorded.
- **[Confirm-ingester connector interface](confirm-connector-interface.md)** — turning a third system's state change (an IdP flag, a closed ticket, a settled payment) into a fulfillment capsule chained to the commitment it confirms; the mock IdP reference implementation and how to wire a real connector.
- **[Signing key management](key-management.md)** — the actual current signer (HMAC-SHA256, self-attested), not a target design.
- **[`guard-check` GitHub Action](ci-action.md)** — pre-merge policy lint + regression replay for your guard config; explicit about what it does *not* cover (your live traffic).
- **[Tenant provisioning](tenant-provisioning.md)** — embedding this package for many customers: one engine instance per tenant (`capsule tenant init`/`upgrade`/`list`), physically separate ledger + manifest + key per tenant.
- **[The judge harness](judge-harness.md)** — model-assisted recorded claims over a conversation: digest-pinned prompts, judgment capsules, MANUAL spot-check adjudication; never in the enforcement path.

## Test data

- **[Test data](test-data.md)** — the fixture ledgers under `tests/fixtures/` and what each one is built to exercise.

## Reference systems

- **[The tau2-airline reference](reference/tau2-airline-reference.md)** — real agent tool-call
  trajectories (one live run, four tau2-bench committed multi-model transcripts), replayed offline
  through the real guard: refusals, an honest capability-gap case, and one row verified offline —
  no API key, no network, under a minute.

## The shape, in one picture

```
  agent action
      │
      ▼
  guard.check(action)             GuardEngine: runs the registered checks (dedupe, caps, ...)
      │
      ├─→ allow ──────────┐
      ├─→ deny             │
      └─→ escalate (hitl_dispatched)
      │                    │
      ▼                    ▼
  capsule appended     (decision recorded either way — no silent drops)
      │
      ▼
  ledger.jsonl             what you keep: an append-only, signed trail of capsules
      │
      ▼
  fold + envelope           `capsule fold test` → {fold digest, range, checkpoint, staleness, result}
      │
      ▼
  bundle / verify            a self-contained slice anyone can verify offline, for free
```

The **capsule** is the record; the **ledger** is where it lives; **folds** turn many capsules into one number you can trust because it comes wrapped in its envelope; **bundle/verify** is how you hand any of this to someone who doesn't already trust you.
