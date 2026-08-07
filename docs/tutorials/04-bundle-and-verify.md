# Bundle and verify

**Goal:** hand someone a slice of your ledger they can verify themselves,
without giving them the whole ledger or access to your systems.

Still using `/tmp/demo-ledger.jsonl` from tutorial 1.

## Cut a self-contained slice: `capsule bundle`

`bundle` takes the same filters as `log` (`--agent`, `--since`/`--until`,
`--counterparty`, `--verdict`, `--action-type`, `--limit`) and writes a
standalone file containing exactly the matching records — plus, per the
tool's own "self-contained" guarantee, any record those cite via
`chain.parent_capsule_id`, walked transitively, so the bundle verifies on
its own without the rest of the ledger present.

```console
$ capsule bundle --ledger /tmp/demo-ledger.jsonl \
    --agent checkout-agent-alpha@v1 --out /tmp/alpha-slice.json
```

```
wrote /tmp/alpha-slice.json (4 record(s), records 3–7, all verify)
checkpoint #7 · as of just now
verify: https://verify.agentactioncapsule.org/bundle#eyJidW5kbGVfdmVyc2lvbiI6...
≡ capsule bundle --agent checkout-agent-alpha@v1 --out /tmp/alpha-slice.json
```

(That `verify:` URL is truncated above — the real one is long. It matters
architecturally: the bundle's entire payload lives *after* the `#`, in the
URL fragment. A fragment is never sent to a server on page load, so nothing
about your ledger's contents leaves your machine just from sharing that
link — only the receiving browser's own JS reads it, the same convention
this workspace's other verify surfaces use.)

## Verify it — as a stranger would

Anyone with the bundle file, and *only* the bundle file, can check it —
no ledger, no key, no account, fully offline:

```console
$ capsule verify --bundle /tmp/alpha-slice.json
```

```
✓ verifies · 25af0ca6c727239efe8bbf1b7e081b32b61787e6d424e4cd8c972ec1e5f86ab8
✓ verifies · 3f469ffa09b1f0e3842c4765e089dd96a8aabd996dea7f5e1547a51ca9d8c5c8
✓ verifies · ee291fae9e673d1b840298ced201c840bc67ebef43ac595af9df19cc534f57a9
✓ verifies · 595847ca81caff1ba96c4d909c43e84d5ff33a8afe0ae554269101c4ee5b965f

bundle /tmp/alpha-slice.json: 4 record(s), verifies clean
```

Each record's own signature and constraint results are checked; add
`--json` for the raw per-record verdicts if you're piping this into
something else.

## Verification is free for anyone

Nothing above needed an account, a paid service, or access to the system
that produced the ledger — `capsule verify --bundle` runs entirely against
the bytes in the file. That's deliberate: a bundle is meant to be handed to
an auditor, a counterparty, or a curious stranger, and checked by them,
independently.

## Where the standards layer lives (and what's not wired up here)

The capsule format this ledger produces is a SCITT/COSE profile
(`draft-mih-scitt-agent-action-capsule`), and the substrate-level
verification underneath it — the raw `COSE_Sign1` signature check, the
transparency-log receipt — is meant to be handled by the standalone
[`scitt-cose`](https://github.com/action-state-group/scitt-cose) project, a
neutral viewer that isn't specific to this repo. `capsule bundle` and
`capsule verify` here call `agent_action_capsule`'s own verifier, which
composes with `scitt-cose` at the payload/substrate boundary described in
that library's docs — but wiring an actual `scitt-cose`-based verification
run wasn't something this tutorial exercised end to end in this
environment, so we're not going to hand you integration steps we didn't
run. What you saw above — `capsule verify --bundle`, no account, no
network call — is the real, working path for "hand this to someone and
have them check it themselves" today.

## You just

Cut a shareable, self-contained slice of your ledger, verified it the way a
stranger would (no ledger, no key, offline, free), and saw honestly where
the deeper standards-layer verification lives and what this tutorial did
and didn't confirm about it.

**That's the whole loop:** generate → read → understand the policy that
gated it → hand off a piece anyone can check.
