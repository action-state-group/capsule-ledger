# Tenant provisioning: one engine instance per tenant

**Status: describes real, tested code — every command below was run
against this repo before it was written down here.**

capsule-ledger is single-org **by scope**: one `LedgerStore`, one policy
manifest, one signing key. If you're embedding this package for many
customers (a SaaS platform, an OEM partner, a multi-tenant orchestrator),
the strongest isolation story is not a multi-tenant ledger process — it's
**one whole engine instance per tenant**: its own ledger directory, its own
policy manifest, its own signing key. Separation is then *physical* — a bug
or a compromise in one tenant's instance cannot reach another's, because
there is no shared process, shared file, or shared key between them.

`capsule tenant init` / `upgrade` / `list` (`capsule_ledger/tenants.py`,
`cli/tenant_cmds.py`) template that instantiation, so provisioning the Nth
tenant is a script, not bespoke work.

## Layout

Every tenant gets its own subdirectory under a `--tenants-root` you choose:

```
<tenants-root>/
  <tenant-id>/
    ledger/                       a LedgerStore root (segments/, index.sqlite3)
    .capsule/
      policy/manifest.yaml        this tenant's own pinned policy manifest
      catalog/folds/...           materialized fold definitions (pack installs only)
      catalog/wickets/...         materialized wicket definitions (pack installs only)
    tenant.json                   provisioning metadata -- see "What's in tenant.json"
```

`tenant-id` becomes a directory name and is validated against
`^[a-z0-9][a-z0-9-]{0,62}$` before anything touches the filesystem — no
`/`, no leading `-`, no `..` segments, so a hostile or mistyped id can't
provision (or overwrite) something outside `--tenants-root`.

## `capsule tenant init`

Provisions a brand-new tenant: creates the ledger, materializes a policy
manifest (the built-in default, or a starter pack via `--pack`), and
appends a first `policy_manifest_activated` capsule to the tenant's own
ledger — so the tenant's epoch history starts from a real, signed record,
not an assumption.

```bash
capsule tenant init --tenants-root ./tenants --tenant-id acme-corp \
    --operator acme-ops --developer acme-agent
```

```
provisioned tenant 'acme-corp' at tenants/acme-corp
  ledger:          tenants/acme-corp/ledger
  manifest:        tenants/acme-corp/.capsule/policy/manifest.yaml
  manifest id:     default/1.0.0
  manifest digest: 0e99f3ee3a6ebf3ee93aa464f27e8fcd1a401ccc45460eb267efde327f5c218c
  activation:      b05d6c3bfc2c39541d836d75066f61a347ca57d580d1770c5c3d4d393931b662
  key id:          acme-corp-signing-key

signing secret (shown once -- this command does not persist it anywhere;
store it in this tenant's own secret manager, not this repo or terminal history):
  9d6b5cec9e09fb08d5f7bffe8a447b8f4a6d3ba556843bead5286244b9d92467
```

To provision a tenant with a starter pack instead of the default manifest:

```bash
capsule tenant init --tenants-root ./tenants --tenant-id widgetco --pack payments-safety
```

`init` refuses (exit 1, nothing written) if the tenant's directory already
exists and has anything in it — provisioning is fail-closed, not
overwrite-by-default. Run `capsule tenant upgrade` for an existing tenant
instead.

### Keys are never written to disk

Same rule as everywhere else in this package
([key-management.md](key-management.md)): a signing secret is either
supplied by you (`--secret`, or `$CAPSULE_MCP_SIGNING_SECRET`) or freshly
generated and printed **once**, to your terminal, for you to hand to that
tenant's own secret manager or environment. `tenant.json` records the key's
**id and fingerprint only** — never the secret — so provisioning metadata
can be inspected, diffed, or committed without leaking key material.

Give each tenant its own key (the default: `<tenant-id>-signing-key` plus a
freshly generated secret). That is what makes the isolation story real: a
compromised key for one tenant can forge capsules for that tenant only.

## `capsule tenant upgrade`

Re-materializes an already-provisioned tenant's manifest — most commonly
because the starter pack it installed shipped a new version, or the
built-in default manifest changed with a package upgrade — and appends a
**new** activation capsule, chained to the tenant's previous one, if and
only if the manifest actually changed:

```bash
capsule tenant upgrade --tenants-root ./tenants --tenant-id widgetco \
    --pack payments-safety --key-id widgetco-signing-key --secret "$WIDGETCO_SECRET"
```

`upgrade` requires the tenant's **current, live** signing key (`--key-id` /
`--secret`, or the env vars) — it is a normal write to that tenant's own
epoch history, not a key rotation. Rotating a tenant's key is
`capsule key rotate`, pointed at that tenant's own ledger
(`--ledger <tenants-root>/<tenant-id>/ledger`); it already works unmodified
against a tenant-provisioned ledger, since a tenant's ledger is a real
`LedgerStore` like any other.

Running `upgrade` when nothing changed is a no-op on the ledger (it prints
"manifest unchanged" and returns 0) — idempotent, so it's safe to run on a
schedule across every tenant without checking first whether anything's due.

`upgrade` refuses (exit 1) if the tenant was never initialized — it will
not silently create one.

## `capsule tenant list`

```bash
capsule tenant list --tenants-root ./tenants
```

```
acme-corp    default/1.0.0                     0e99f3ee3a6ebf3e…  key=acme-corp-signing-key
widgetco     asg.payments_safety.install/1.0.0  c03bd8ee6e655744…  key=widgetco-signing-key
```

One line per tenant with a `tenant.json`, from that file alone — a tenant
directory with no `tenant.json` (an `init` that never finished) is skipped,
not guessed at.

## What's in `tenant.json`

```json
{
  "tenant_id": "acme-corp",
  "manifest_id": "default/1.0.0",
  "manifest_digest": "0e99f3ee3a6ebf3ee93aa464f27e8fcd1a401ccc45460eb267efde327f5c218c",
  "pack_id": null,
  "key_id": "acme-corp-signing-key",
  "key_fingerprint": "6d137396a0088ec355227d5927940cf9d525ff50910cee5f0067fc8f3bad97b9",
  "activation_capsule_id": "b05d6c3bfc2c39541d836d75066f61a347ca57d580d1770c5c3d4d393931b662"
}
```

This is provisioning metadata for your own tooling (a fleet dashboard, a
drift check comparing `manifest_digest` against what's actually activated
on each tenant's ledger) — it is not itself a signed record. The signed,
tamper-evident history lives in each tenant's own `ledger/`, readable with
the same verbs as any other capsule-ledger instance:
`capsule manifest verify`, `capsule log`, `capsule verify`.

## Running each tenant's engine

Provisioning creates the files; running the engine against them is the
same as running capsule-ledger anywhere else, pointed at that tenant's own
paths:

```bash
export CAPSULE_LEDGER=./tenants/acme-corp/ledger
export CAPSULE_MCP_SIGNING_KEY_ID=acme-corp-signing-key
export CAPSULE_MCP_SIGNING_SECRET="$ACME_CORP_SECRET"     # from your secret manager, never this repo
capsule log
```

In a real per-tenant deployment (a sidecar or namespace per customer in
your own orchestration layer, per the embedding pattern this kit exists
for), that's one process per tenant, each with its own environment — no
per-tenant namespacing of env vars is needed, because each instance is
already a separate process pointed at its own tenant directory.

## What this doesn't do

- It doesn't run anything for you — no scheduler, no per-tenant process
  supervision. That's your orchestration layer's job; this kit only
  templates the files and the first/next activation capsule.
- It doesn't create a shared multi-tenant view across instances. Each
  tenant's ledger verifies independently, by construction; a fleet-wide
  read (e.g. "every tenant's current manifest digest") is
  `capsule tenant list` plus your own aggregation, not a feature of any
  one tenant's engine.
- There's no per-tenant custom-manifest authoring surface at the CLI beyond
  `--pack` (the built-in default manifest is used when `--pack` is
  omitted) — this kit templates *provisioning*, not manifest design; author
  a manifest or a pack with `capsule manifest`/`capsule init --pack` first.
