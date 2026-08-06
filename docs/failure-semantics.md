# Guard failure semantics

**Principle: fail closed for consequential action classes, fail open only
where a class has explicitly configured it, and every degradation is
recorded — never silent.** A guard that silently stops guarding is worse
than no guard, because everyone still believes it is on.

| Condition | Behavior | Recorded |
|---|---|---|
| Ledger append fails (disk full, WAL error) | **Fail closed** for consequential classes; the action does not dispatch | A degradation record on recovery, naming the gap window |
| Local view unavailable or corrupt | **Fail closed**; the view is rebuilt by replay, then decisions resume | A rebuild event, naming the range replayed |
| View is stale beyond the declared freshness bound | **Per-class policy** — fail closed by default for money and irreversible classes; fail open only for a class explicitly configured for it | Staleness (checkpoint age) recorded on the decision either way |
| Guard engine unreachable | **Fail closed** by default; fail open requires an explicit per-class opt-in that names the risk | Every fail-open dispatch is recorded as reduced-assurance |
| Anchor or witness unreachable | **Never blocks** — anchoring is asynchronous; the record is complete without it | The record is reported unanchored until a checkpoint lands |
| Signing key unavailable | **Fail closed** — an unsigned record is not a record | An operator-alert record, produced on recovery |

**Non-negotiables:**
- Fail-open is never a default and never implicit — it is a configuration a
  human named, per action class.
- Degradation is always recorded, never silent, even when the record can
  only be written after the fact (on the next successful decision).
- An action with **no declared class** is treated as **consequential —
  fail closed**. This is the default every other row protects: an
  unclassified action does not get to skip the table by omission. A small
  starter class taxonomy ships so day-one use is not blocked on everything
  — see `capsule_ledger/guards/classes.py`.

## What this means in practice

Every decision the guard returns carries: which constraints were evaluated
and their result, the fold evidence any constraint read, and the checkpoint
age at decision time. When a decision cannot be safely recorded at all (a
failed ledger append, or an unavailable signing key), the guard still fails
closed — it just cannot produce a capsule for that specific decision, and
the fact of the degradation is written as soon as it safely can be, on the
next successful decision.

This is the guard API's implementation of that table, not a restatement of
it — see `capsule_ledger/guards/engine.py`, and the failure-semantics test
matrix in `tests/test_guard_failure_semantics.py` (one test per row above).
