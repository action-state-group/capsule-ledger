# Signing key management

**Status: this describes the actual current mechanism.**
v0 has no COSE/asymmetric signer anywhere in this package. Every capsule this
package produces is `attestation_mode: self_attested`, sealed with a local
HMAC-SHA256 "signature" (see `capsule_ledger/guards/signing.py`) — enough to make
key material a real, checkable precondition for [the fail-closed rule on an
unavailable signing key](failure-semantics.md), and to make the signature
itself tamper-evident (it is committed into `capsule_id`), without pulling in
a cryptography dependency this package doesn't otherwise need. 

| Question | Current answer |
|---|---|
| Key type | HMAC-SHA256 shared secret (`LocalSigner`), not an asymmetric keypair |
| Provisioning | Caller-supplied: whatever constructs a `LocalSigner` (or a `signer_provider` passed to `GuardEngine`) picks the key id/secret. This package itself has no live decision-producing entry point (CLI is read/verify only) — see "Provisioning today" below for where provisioning actually happens now |
| Where the key lives on disk | Nowhere, by design — `LocalSigner` takes the key id/secret as constructor arguments; there is no key file, keystore, or on-disk secret store in this package |
| Scope | One key per `LocalSigner` instance, held in memory for the caller's process lifetime; not shared across processes or persisted |
| Rotation | Not implemented. Constructing a new `LocalSigner` with a new key starts signing new decisions with it; nothing in this package records that a rotation happened, revokes the old key, or re-signs anything |
| Key loss / compromise | Not detected or handled specially. A compromised secret can forge capsules indistinguishable from genuine ones until the caller rotates it out-of-band; there is no revocation list, no key-compromise event, and no way to invalidate capsules signed under a known-bad key |

## Provisioning today

`LocalSigner` (`capsule_ledger/guards/signing.py`) is a plain constructor — this
package has no key-generation step, ceremony, or CLI verb of its own; every
caller supplies its own key id/secret. The MCP advisory server that used to
live here (`capsule_ledger/mcp/`, `intent_declare` tool) provisioned one via
two env vars and shipped a checked-in dev-default key; that server — and its
provisioning story — now lives in `capsule-engine`, not this package. See
`docs/onboarding.md`'s Path 2 (`framework_adapter_example.py`) for how an
in-process caller in this repo constructs one directly.

The dry-run report builder that used to live here (`capsule_ledger/report/`,
`capsule guard dry-run` in `capsule-engine`) constructed its own `LocalSigner`
with a hardcoded key (`key_id="dry-run-report"`) to produce a read-only replay
artifact, unrelated to any live decision path; that builder now lives in
`capsule-engine` too. `GuardEngine.check(..., dry_run=...)` is the only thing
in this package that ever gates a real decision.

## Key loss or compromise, today

There is no rotation or revocation mechanism in `LocalSigner` itself, so
recovery is entirely out-of-band and manual for whatever caller provisions
it:
1. Generate a new secret and construct a new `LocalSigner` (or reconfigure
   whatever `signer_provider` supplies one) with it.
2. Nothing marks the old key as revoked, records the compromise, or
   distinguishes capsules signed before vs. after the change — a verifier
   checking `key_id` will see the two periods only as different `key_id`
   values, with no signal that one of them should not be trusted.

This matches [failure-semantics.md](failure-semantics.md)'s "signing key
unavailable" row for the case where no key is configured at all (the engine
fails closed and denies), but a *compromised-while-still-present* key is not
covered by that row — the engine has no way to know a key it can still use
is one it shouldn't.
