# OSS/Paid Boundary Policy

This document states what belongs in this repository and what does not, so that
contributors and operators can place a feature without asking.

## The line

This repository ships the **local control-plane** for an agent ledger: the append-only
log, guard checks, verifiable folds, and the primitives needed to emit and verify a
signed checkpoint against any conforming SCITT Transparency Service. That is the whole
OSS surface.

The **operated service layer** — scheduling, timing guarantees, multi-tenant
unattributability, operated anchors with uptime SLAs — is a separate paid tier and is
not built here.

## Five tests

Run these in order. The first test that gives a definitive answer settles it; no need to
run the others.

### 1. Counterparty interoperability test

> *Would a counterparty deploying their own ledger need this feature to interoperate
> with records produced by another party's ledger?*

**Yes → OSS substrate.** Protocol primitives — checkpoint format, receipt schema, MMR
node layout, wire representation — must be public and identical across implementations.
Hiding them breaks interoperability.

**No → proceed to test 2.**

### 2. Operator-independence test

> *Can the feature run entirely on the deployer's own infrastructure, using only their
> own keys and their own cron, with no component operated by anyone else?*

**Yes → OSS.** The feature is a local capability. Operators must be able to self-host it
from source.

**No → proceed to test 3.**

### 3. Neutral protocol test

> *Is the feature a specification-level primitive — a format, encoding, or algorithm —
> that a standards body or independent implementer would need to describe precisely?*

**Yes → OSS.** The spec surface is always public. Obscuring a protocol primitive does
not protect it; it only fragments the ecosystem.

**No → proceed to test 4.**

### 4. Operated service test

> *Does the feature's value require an always-on service operated by someone other than
> the deployer — scheduling, jitter, SLA guarantees, operated anchor roots?*

**Yes → Paid Cloud tier. Do not build it here.** Features in this category include
fixed-cadence checkpoint scheduling with timing guarantees, automatic key rotation as a
service, and operated anchor infrastructure with uptime contracts. These belong in the
hosted product, not in the library.

**No → proceed to test 5.**

### 5. Unattributability / volume-privacy test

> *Does the feature's value derive from obscuring which operator produced a record, or
> from making volume patterns unattributable across tenants?*

**Yes → Paid Cloud tier. Do not build it here.** Timing jitter, batch-mixing across
tenants, and volume-unattributability require an operated multi-tenant environment to
mean anything. They cannot be provided by a library the operator runs on their own
hardware, and shipping a non-functional stub is worse than not shipping at all.

**No → the feature is OSS.** Build it here.

## Quick reference

| Feature | Tests | Verdict |
|---------|-------|---------|
| MMR append, peak hash, root computation | 1, 2, 3 | OSS |
| Signed checkpoint format (mmr_size, peaks_digest, key_id, timestamp) | 1, 3 | OSS |
| Register checkpoint at a SCITT TS, store COSE receipt | 2 | OSS |
| Verify inclusion-to-peak + checkpoint + receipt chain | 1, 2 | OSS |
| Fixed-cadence checkpoint trigger (operator's own cron) | 2 | OSS |
| Operated checkpoint scheduling (ASG-run, SLA-backed) | 4 | **Paid** |
| Timing jitter across checkpoints | 5 | **Paid** |
| Volume unattributability across tenants | 5 | **Paid** |
| Operated anchor with uptime contract | 4 | **Paid** |

## Rationale

The boundary is drawn at *independence*. A feature is OSS when an operator can deploy it
entirely from this source, verify it from this source, and rely on it without calling
home. A feature is Paid when its security or privacy property only exists in an operated
multi-tenant context — the source alone cannot deliver the property, so shipping the
source alone ships a fiction.

This is not a restriction on OSS contributors. It is a clarity rule: features that
cannot be tested in isolation, verified in isolation, or reasoned about in isolation
belong in the service layer that provides the context they need.
