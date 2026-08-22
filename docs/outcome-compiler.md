# The outcome compiler

**Status: built, but not yet on `main`.** Everything on this page runs today from a
branch checkout — see [Where this lives](#where-this-lives) at the bottom before you
start. If the word "compiler" is new to you in this repo, you're not missing
something: this is currently the only doc that explains it.

## What it is, in one paragraph

You write **one plain-English statement** about an outcome you care about — "every
refund over $500 is approved by a manager before it's issued." The compiler turns
that one statement into **two independent checks bound together**: a **guard**
that runs *before* the action (forward), and a **fold** that can prove it happened
*from the record alone, after the fact* (backward). Both checks are compiled from
the same declaration and sealed into one **compilation record**, so the two halves
cannot silently drift apart — a guard that allows something and a fold that can't
find it would mean the record is lying about what was actually checked, and this is
the machinery that makes that impossible instead of just unlikely.

You never hand-write the guard or the fold yourself. You write the statement; the
compiler decides, honestly, whether either half can even be built — and says so in
plain English, not a percentage.

## Try it in two commands

```console
$ capsule setup init
instance ready: .capsule-setup
  ...
    export CAPSULE_SETUP_SIGNING_KEY_ID=capsule-setup-key
    export CAPSULE_SETUP_SIGNING_SECRET=<a freshly generated secret>

$ export CAPSULE_SETUP_SIGNING_KEY_ID=capsule-setup-key   # from above
$ export CAPSULE_SETUP_SIGNING_SECRET=<paste the secret from above>
$ capsule setup propose \
    --statement "a refund action_class:refund_issued was confirmed by the billing system" \
    --outcome-id acme.refund_confirmed \
    --drafter static

  ✓ acme.refund_confirmed
      forward: checked automatically before the action ran · backward: provable from the record alone
      provable on 0 of 0 dispatches (0%)
      evidence rule: a 'refund_issued' dispatch chained to a confirmation with status=confirmed
```

That's a real, honest verdict on a statement you just wrote — no trace file, no
model call (`--drafter static` is a zero-network reference drafter), nothing
hand-mapped in advance. `0 of 0 dispatches` is not a bug: this fresh instance has
never recorded a `refund_issued` dispatch, so the coverage is honestly empty. The
verdict pair itself (forward/backward) never depends on how much evidence exists —
only on whether the *kind* of claim is checkable at all (see [The verdict
pair](#the-verdict-pair-what-youre-actually-being-told) below).

### The `--statement` mini-grammar (for `--drafter static`)

`--drafter static` is a deterministic, no-network reference implementation, not
real language understanding — it exists so you can try the whole path with zero
setup and zero API key. It looks for one inline hint plus one trigger word:

| you want a...        | trigger word (anywhere in the sentence) | required hint                    |
|-----------------------|------------------------------------------|-----------------------------------|
| **attainment** claim (`X was confirmed`) | `confirmed`                    | `action_class:<your_id>`          |
| **offer/response** claim (`someone was offered a choice`) | `offer`, `offered`, `offering` | `offer_namespace:<your_id>` (optional; defaults to `advisory`) |
| **decision** claim (`X was authorized`) | `authorized`, `authorization`  | `action_class:<your_id>`          |

The hint is stripped before the statement is stored — it never appears in the
persisted, disclosable `statement` field, only in what you type on the command
line. A statement matching none of these is **not an error** — it's reported as
`REFUSED -- no known evidence rule can check this statement at all`, honestly,
because the static drafter's grammar really is this small. For real free text with
no hint syntax, use `--drafter deepeval` instead (requires `pip install
capsule-ledger[judge]` and a model; see `docs/judge-harness.md` for the BYOM
pattern this reuses) — same command, same output shape, same deterministic verdict
computation underneath; only the *rationale prose* and how the candidate structure
gets drafted differ.

## The verdict pair: what you're actually being told

Every compiled statement gets **two** verdicts, not one — a forward and a
backward, because "checked before it happens" and "provable after the fact" are
genuinely different claims and conflating them is how compliance theater happens.

**Forward** (can this be checked *before* the action runs):

| verdict | plain English |
|---|---|
| `DETERMINISTIC` | checked automatically before the action ran |
| `UNAVAILABLE-MODEL-REQUIRED` | not checked before the action ran — would need a live judgment call |
| `UNAVAILABLE-STATE-REQUIRED` | not checked before the action ran — the needed record did not exist yet |
| `REFUSED` | no automatic check exists for this claim |

**Backward** (can this be proven *from the record*, after the fact):

| verdict | plain English |
|---|---|
| `DETERMINISTIC` | provable from the record alone |
| `MODEL-ASSISTED` | provable with a reviewer's judgment over the record |
| `MANUAL` | provable only by a person attesting to it directly |
| `WITH-INSTRUMENTATION` | provable once a missing record is captured; not claimed today |
| `REFUSED` | this claim cannot be decomposed into evidence that would prove it |

**A `REFUSED` verdict is a successful, working answer, not an error or a bug.**
Some claims genuinely cannot be checked from any record — "the interaction
increased the counterparty's trust in the system" is a real example this repo's
own default candidate catalog carries, refused on purpose, because no ledger
entry could ever settle whether trust changed. A tool that says so, in one plain
sentence, instead of quietly inventing a number, is the point. (If the very first
thing you ever run is `capsule setup propose` on a brand-new instance with no
`--statement`, you'll see two of these built-in refusals and nothing else — that's
the demo catalog being honest about the two hardest claims it knows about, not the
compiler being broken. Run the two-command walkthrough above with your own
statement first if you want a `DETERMINISTIC` win to look at instead.)

## The full loop: author → accept → enforce

`propose` only ever produces a **proposal** — confirming and enforcing it are
separate, human steps, on purpose (design's own "recorded act, never a config
edit" rule: nothing here is a file you hand-edit into effect).

```console
$ capsule setup confirm accept --outcome-id acme.refund_confirmed
T1 accepted acme.refund_confirmed: 878e8d2d...   # freezes the compilation record

$ capsule setup enforce shadow --outcome-id acme.refund_confirmed
shadow report for acme.refund_confirmed: 0 historical action(s), 0 would have been refused

$ capsule setup enforce promote --outcome-id acme.refund_confirmed
promoted acme.refund_confirmed to enforce (shadow: 0 total, 0 would-fail): b51ae08b...

$ capsule setup enforce dispatch --outcome-id acme.refund_confirmed --verb refund_issued
ALLOW 05083530...

$ capsule setup enforce dispatch --outcome-id acme.refund_confirmed --verb delete_account
DENY a5b68002...
reproduce: capsule verify a5b68002... --refusal --declarations .capsule-setup
```

Only an **attainment** candidate (the `action_class:` shape above) has anything to
enforce — its forward verdict is the only one that ever reaches `DETERMINISTIC`
through today's real evidence rules, so it's the only kind `enforce` will accept.
`offer_response` and `decision` candidates are declare-and-observe only for now.

The four touchpoints, if you want the names used elsewhere in this repo's design
docs and code comments:

- **T1** (`confirm accept`) — freeze the declaration's compilation record.
- **T2** (`confirm census`) — sign off on N of M outcomes in a document, independent
  of any one outcome_id.
- **T3** (`enforce promote`) — after a shadow report, actually gate live traffic.
- **T4** (`confirm acknowledge-refusal`) — a human sees and accepts a `REFUSED`
  verdict, so the refusal is a recorded acknowledgment, not a silently-missing
  feature.

`capsule setup status` any time shows every declaration you've authored, its
acceptance state, and its verdict pair in the same plain English as above.

## Where this evidence comes from

Instead of hand-typing `--statement`, `capsule setup observe --input
<trace.jsonl>` records real traffic (dispatches, confirmations, offers,
responses) at the emit layer with zero enforcement, and a batch `capsule setup
propose` (no `--statement`) grades a fixed built-in candidate catalog against
whatever it finds — same verdicts, same plain English, coverage computed from
real traces instead of zero. There's no `--example`/`--demo-trace` flag yet; the
committed fixture files under `tests/fixtures/setup/*.jsonl` are real,
schema-valid input for `--input` if you want to see this path without writing
your own trace — each line is one JSON event dict, `{"kind": "dispatch", ...}` /
`{"kind": "confirmation", ...}` / `{"kind": "offer", ...}` / `{"kind":
"response", ...}` (see `capsule_ledger/setup/observe.py` for the exact per-kind
shape each `kind` expects).

## A hand-authored declaration is a real input, not write-only output

Every command above writes JSON files under `.capsule-setup/declarations/`. That
directory is a real store, not a log: `capsule setup status` (and everything else
that reads a declaration) picks up a file placed there by any means, as long as
it's shaped like what `propose` itself writes — you are not limited to the CLI's
own drafters if you'd rather assemble a declaration by another route. A file that
*isn't* readable (invalid JSON, or missing the required keys) is reported loudly,
by name, rather than silently skipped or ignored.

## Where this lives

The compiler (`capsule_ledger.compiler`), the `capsule setup` verbs
(`capsule_ledger.setup`), and the `--statement` authoring path above are complete
and tested, but the branch stack that built them hasn't merged to `main` yet. To
run anything on this page today, check out `ldg-english-to-declaration-drafter`
(the current tip; it already contains everything the other branches below add) —
open PRs, oldest dependency first: `ldg-cs-p1-schema`, `ldg-plan-containment-not-in-main`,
`ldg-cs-p2-compiler-core`, `ldg-cs-p3-setup-verbs`, `ldg-live-compile-demo`,
`ldg-propose-airline-corpus-bridge`, `ldg-propose-live-drafting-mode`,
`ldg-english-to-declaration-drafter`. A separate, sibling branch
(`ldg-airline-engagement-pack`) applies these same verdicts to a real
tau2-bench airline conversation corpus but isn't part of this stack yet, so no
single checkout currently has both.
