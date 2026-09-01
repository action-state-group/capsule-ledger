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
| Provisioning | Set two env vars on the MCP server process: `CAPSULE_MCP_SIGNING_KEY_ID`, `CAPSULE_MCP_SIGNING_SECRET` |
| Default if unset | A **fixed, checked-in dev key** (`key_id="capsule-mcp-server"`, secret `b"capsule-mcp-server-dev-key"`) so the server runs out of the box for local experimentation |
| Where the key lives on disk | Nowhere, by design — it exists only as an env var value or the in-source dev-key fallback; there is no key file, keystore, or on-disk secret store in this package |
| Scope | One key per running server process, held in memory for the process lifetime; not shared across processes or persisted between restarts unless the same env vars are set again |
| Rotation | Not implemented. Restarting the process with new env vars starts signing new decisions with the new key; nothing in this package records that a rotation happened, revokes the old key, or re-signs anything |
| Key loss / compromise | Not detected or handled specially. A compromised secret can forge capsules indistinguishable from genuine ones until an operator rotates it out-of-band; there is no revocation list, no key-compromise event, and no way to invalidate capsules signed under a known-bad key |

## Provisioning today

The only live signing path is the MCP server's `intent.declare` tool
(`capsule_ledger/mcp/server.py`, `_get_guard`): it builds one `LocalSigner` from
`ServerConfig.signing_key_id` / `signing_secret` at first use and reuses it
for the life of the process (`capsule_ledger/mcp/config.py`, `load_config`).
There is no key-generation step, ceremony, or CLI verb — an operator sets
the two env vars (or accepts the dev default) before starting the server.

One other place constructs a `LocalSigner`, and it is not the live decision
path: `capsule_ledger/report/replay.py`'s dry-run report builder uses its own
hardcoded key (`key_id="dry-run-report"`) to produce a read-only replay
artifact, unrelated to the MCP server's key. `GuardEngine.check(...,
dry_run=...)` is the only thing that ever gates a real decision.

## The dev-default key is not a secret boundary

`_DEFAULT_SIGNING_SECRET` in `capsule_ledger/mcp/config.py` is a literal string
checked into source. It exists so the server runs immediately with no setup;
it provides no confidentiality once the source is public (flagged in PR
#13). Anything beyond local experimentation must set both
`CAPSULE_MCP_SIGNING_KEY_ID` and `CAPSULE_MCP_SIGNING_SECRET` explicitly — running
the dev default in a shared or production deployment means anyone who has
read the source can forge signed capsules.

## Key loss or compromise, today

There is no rotation or revocation mechanism, so recovery is entirely
out-of-band and manual:
1. Generate a new secret and set it via `CAPSULE_MCP_SIGNING_SECRET` /
   `CAPSULE_MCP_SIGNING_KEY_ID`.
2. Restart the MCP server process. It picks up the new key on next launch
   (`load_config()` reads the environment once, at construction).
3. Nothing marks the old key as revoked, records the compromise, or
   distinguishes capsules signed before vs. after the change — a verifier
   checking `key_id` will see the two periods only as different `key_id`
   values, with no signal that one of them should not be trusted.

This matches [failure-semantics.md](failure-semantics.md)'s "signing key
unavailable" row for the case where no key is configured at all (the engine
fails closed and denies), but a *compromised-while-still-present* key is not
covered by that row — the engine has no way to know a key it can still use
is one it shouldn't.
