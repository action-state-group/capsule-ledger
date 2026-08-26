# OSS Project Scope

This document states what belongs in this repository and what does not, so that
contributors and operators can place a feature without asking.

## The Scope

This repository ships the **local control-plane** for an agent action ledger: the append-only
log, guard checks, verifiable folds, and the primitives needed to emit and verify a
signed checkpoint against any conforming SCITT Transparency Service. That is the whole
OSS surface. Operated service layers are not in scope. 

## Five tests

Run these in order. The first test that gives a definitive answer settles it; no need to
run the others.

### 1. Counterparty interoperability test

> *Would a counterparty deploying their own ledger need this feature to interoperate
> with records produced by another party's ledger?*

**Yes → OSS scopoe.** Protocol primitives — checkpoint format, receipt schema, MMR
node layout, wire representation — must be public and identical across implementations.
Hiding them breaks interoperability.

**No → proceed to test 2.**

### 2. Operator-independence test

> *Can the feature run entirely on the deployer's own infrastructure, using only their
> own keys and their own cron, with no component operated by anyone else?*

**Yes → OSS scope.** The feature is a local capability. Operators must be able to self-host it
from source.

**No → proceed to test 3.**

### 3. Neutral protocol test

> *Is the feature a specification-level primitive — a format, encoding, or algorithm —
> that a standards body or independent implementer would need to describe precisely?*

**Yes → OSS scope.** The spec surface is always public. Obscuring a protocol primitive does
not protect it; it only fragments the ecosystem.

**No → proceed to test 4.**

### 4. Operated service test

> *Does the feature's value require an always-on service operated by someone other than
> the deployer?*

**Yes → not OSS scope.** Features in this category include typical service offerings. 

**No → proceed to test 5.**

### 5. Unattributability / volume-privacy test

> *Does the feature's value derive from obscuring which operator produced a record, or
> from making volume patterns unattributable across tenants?*

**Yes → not in OSS scope.** Cannot be provided by a library the operator runs on their own
hardware, and shipping a non-functional stub is worse than not shipping at all.

**No → the feature is OSS scope.** Build it here.

## Quick reference

| Feature | Tests | Verdict |
|---------|-------|---------|
| MMR append, peak hash, root computation | 1, 2, 3 | OSS — consumed from the neutral `capsule_emit.checkpoint` core, not forked here |
| Signed checkpoint format (mmr_size, root, key_id, timestamp) | 1, 3 | OSS — consumed from the neutral `capsule_emit.checkpoint` core, not forked here |
| Register checkpoint at a SCITT TS, store COSE receipt | 2 | OSS |
| Verify inclusion-to-peak + checkpoint + receipt chain | 1, 2 | OSS |
| Fixed-cadence checkpoint trigger (operator's own cron) | 2 | OSS |

The first two rows pass test 1 (counterparty interoperability) precisely because they are
substrate a counterparty needs to verify this ledger's log — that is what places them in the
neutral producer library (`capsule-emit`'s `checkpoint` subpackage) rather than as a
capsule-ledger-local implementation. capsule-ledger imports that public interface; it never
maintains a second copy of the MMR algorithm.

## Rationale

The OSS scope is drawn at *independence*. A feature is OSS when an operator can deploy it
entirely from this source, verify it from this source, and rely on it without calling
home. A feature that the source alone cannot deliver a security or privacy property is not it scope as shipping the source alone ships a fiction.

This is not a restriction on OSS contributors. It is a clarity rule: features must be
testable in isolation, verifiable in isolation, and reasoned about in isolation.
