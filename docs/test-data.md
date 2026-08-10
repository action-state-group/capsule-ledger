# Test-data guide

What lives in `tests/fixtures/`, how one of them doubles as a fixture
*generator*, and how the test suite actually uses each file. Every command
below was run against this checkout.

## The fixtures

```console
$ wc -l /tmp/cl/tests/fixtures/*.jsonl /tmp/cl/tests/fixtures/*.json
```

```
    4 amaury_sample_ledger.jsonl
   36 nanda_transaction_ledger.jsonl
    4 sample_ledger.jsonl
    7 two_agents_sim_ledger.jsonl
  432 mcp_tool_schema_snapshot.json
```

- **`sample_ledger.jsonl`** (4 capsules) — a checked-in copy of
  `capsule-emit`'s own `examples/amaury-receipt-pack/sample_ledger.jsonl`
  fixture, copied into this repo so CI (which only checks out
  `capsule-ledger`, not a sibling `capsule-emit` checkout) can replay it
  without an external dependency. Per `tests/test_cli_fold.py`'s own module
  docstring, this is "the fixture named in the T1 acceptance criteria."
  General-purpose: small enough to eyeball, used as the default fixture
  across most CLI tests.

- **`amaury_sample_ledger.jsonl`** (4 capsules) — a second, distinct sample
  built around a `transfer_funds`/`approve_purchase`-style flow, used
  specifically to demonstrate the **caps** check: `tests/test_guard_dry_run.py`
  notes it "demonstrates the same [dedupe-style repeat scenario] for the
  caps check, in dry_run form," and cross-references
  `test_guard_eur150k_bridge.py` for "the non-dry-run, actually-recorded
  version of the same action -- it escalates rather than blocks."

- **`nanda_transaction_ledger.jsonl`** (36 capsules) — a "tax-audit-style"
  fixture (`tests/test_cli_diff.py`'s own description) of 36 near-identical
  `record_transaction` capsules: same operator/developer/action_type, no
  discriminating amount or target. `tests/test_guard_dry_run.py` spells out
  why: "replaying them one at a time is exactly the dedupe check's target
  case: the first occurrence passes, every repeat would-have-held." It's
  also the fixture that's actually large enough to exercise `capsule lens
  shape`'s retry-storm detection meaningfully (tutorial 2's fixture only has
  7 records — too few to trip it).

- **`two_agents_sim_ledger.jsonl`** (7 capsules) — the byte-identical output
  of the two-agent simulator (`python -m capsule_ledger.examples.two_agents`)
  at its default seed. This is the fixture the tutorials series
  (`docs/tutorials/`) is built on, generated fresh in tutorial 1 rather than
  read from this checked-in copy — see "the simulator as fixture generator"
  below for why those two are byte-identical, checked directly rather than
  assumed.

- **`mcp_tool_schema_snapshot.json`** (432 lines, 10 tool entries: e.g.
  `action_been_done`, `budget_remaining`, `constraints_list`,
  `decision_explain`, `fold_get`, `fold_list`, `intent_declare`,
  `ledger_query`, `record_get`, `record_verify`) — not a ledger at all. Per
  `tests/test_mcp_schema.py`'s docstring, it "pins the exact
  name/description/inputSchema of every MCP tool this server exposes, so a
  future accidental signature change ... is caught by a diff against"
  this file, "rather than discovered by a caller at runtime." It's a schema
  snapshot, checked against `capsule_ledger.mcp.server`'s live tool
  registration — no ledger is opened to produce or check it.

## The two-agent simulator doubles as fixture generator

`capsule_ledger/examples/two_agents.py` is explicitly both a demo you run
and the thing that produced `two_agents_sim_ledger.jsonl`. Its `--out` flag
controls where the flat JSONL fixture is written; the module's own default
for `--out` is that exact fixture path
(`tests/fixtures/two_agents_sim_ledger.jsonl`), and its default `--seed`
(`20260807`, a fixed constant in the code — it only *looks* like today's
date) is what makes regeneration reproducible:

```console
$ python -m capsule_ledger.examples.two_agents --out /tmp/demo-ledger.jsonl
$ md5sum /tmp/cl/tests/fixtures/two_agents_sim_ledger.jsonl /tmp/demo-ledger.jsonl
```

```
a8f2c3afbfb257d05fdefadd67b55020  /tmp/cl/tests/fixtures/two_agents_sim_ledger.jsonl
a8f2c3afbfb257d05fdefadd67b55020  /tmp/demo-ledger.jsonl
```

Byte-identical — confirmed against this checkout, not asserted. Running it
twice more, to two different output paths, also produces two identical
files to each other. The module's own docstring explains the mechanism: every
`Action` gets an explicit `action_id`/`timestamp` instead of the
wall-clock/`uuid4()` defaults, and a `_pinned_capsule_emit_clock` context
manager pins the one call into `capsule-emit`'s own `emit()` (used for the
`intent.declare` capsule) that would otherwise read the wall clock and
generate a random uuid internally. Everything — both agents' signing keys,
the intent capsule's synthetic id, every timestamp — derives from
`--seed`; change the seed and you get a genuinely different (but still
internally reproducible) ledger.

`tests/test_two_agents_example.py` is the test that holds this contract:
it runs the simulator in-process and asserts its output against the
checked-in `two_agents_sim_ledger.jsonl`, so a change to the simulator that
silently breaks determinism (or changes the scripted scenarios) fails CI
rather than being noticed only when someone's tutorial output stops
matching.

## `payments-safety` pack fixture

`capsule_ledger/packs/catalog/payments-safety/fixtures/mini_ledger.jsonl`
(6 capsules: 1 policy-manifest activation + 5 guard decisions) is the
starter pack's own acceptance fixture — generated the same way
`two_agents_sim_ledger.jsonl` is, by running `tests/test_pack_payments_safety_acceptance.py`
directly rather than through pytest:

```console
$ PYTHONPATH=. python3 tests/test_pack_payments_safety_acceptance.py
wrote 6 record(s) to .../packs/catalog/payments-safety/fixtures/mini_ledger.jsonl
```

Every fixed input (action ids, timestamps, the activation capsule's own
action id, the signing key's secret) is hardcoded in that script the same
way `two_agents.py` hardcodes its own — no wall clock, no `uuid4()`
default, so re-running it reproduces this exact file. The scenario set
exercises every one of the pack's three obligations *both ways*: `caps`
(pass, then fail → escalate — `money.transfer` has an `approver_role`, so a
sole `caps` failure escalates rather than denies, same D2 rule the two-agent
sim's own overlap-spend scenario exercises), `dedupe` (pass, then fail →
deny), and `verify_before_dispatch` (fail by way of a cited mandate that was
never recorded → deny). `test_fixture_is_reproducible_byte_for_byte`
(same file) holds this contract in CI: it re-runs the scenario script
in-process and diffs the result against the checked-in bytes.

No plaintext PII: every `target`/counterparty reference is a synthetic
`vendor-<name>/invoice-<n>` string, and the one `cited_mandate_capsule_id`
used to trigger the `verify_before_dispatch` refusal is the same
obviously-synthetic `"f" * 64` sentinel `two_agents.py`'s own refusal
scenario uses — never a real-looking id.

## How the test suite uses these fixtures

A few real examples (there are more — grep `tests/` for a fixture's name to
find every consumer):

- **`tests/test_cli_fold.py`** — loads `sample_ledger.jsonl` as
  `FIXTURE_LEDGER` and calls `capsule fold list` / fold replay against it,
  to check the fold catalog and replay-over-a-ledger path both work against
  a real, small ledger.

- **`tests/test_cli_diff.py`** — loads both `AMAURY` and `NANDA` fixtures;
  its module docstring states the acceptance bar directly: "a meaningful
  before/after diff on the tax-audit-style fixture
  (`nanda_transaction_ledger.jsonl`)" is what `test_nanda_before_after_diff_is_meaningful`
  exists to prove.

- **`tests/test_cli_bisect.py`** — loads both `AMAURY` and `NANDA`; e.g.
  `test_bisect_verdict_finds_first_matching_record` asserts `capsule
  bisect --verdict blocked --ledger <AMAURY>` finds the exact known
  first-blocked capsule id (`cd0692b3…`) at the exact known sequence
  position ("seq: #2 (of 4)") — a golden-output test pinned against the
  fixture's real, checked-in bytes, not a mock.

- **`tests/test_guard_eur150k_bridge.py`** and **`tests/test_guard_dry_run.py`**
  — both load `AMAURY`/`NANDA` specifically to exercise the caps and
  dedupe checks' dry-run vs. actually-recorded behavior against real,
  reproducible transaction shapes rather than hand-rolled one-off capsules.

- **`tests/test_mcp_schema.py`** — loads `mcp_tool_schema_snapshot.json` and
  diffs it against the live tool list from `capsule_ledger.mcp.server`,
  failing loudly ("intentional change, update
  tests/fixtures/mcp_tool_schema_snapshot.json") if a tool's schema drifts
  without the snapshot being updated deliberately.

- **`tests/test_two_agents_example.py`** — the determinism contract test
  described above, the one directly responsible for
  `two_agents_sim_ledger.jsonl` staying trustworthy as a fixture.
