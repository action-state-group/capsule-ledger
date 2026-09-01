#!/usr/bin/env python3
"""F.3 re-arm gate — bounce any PR that adds/grows content in a bucket this
repo no longer owns.

Amendment H.3 / [ldg-ledger-scope-re-extraction]: post-move capsule-ledger is
F.1 item 1's honest-records core ONLY (store, chains, refusals, CLL
consumption, read/verify seam). The 2026-08-22 ratified PR-target map already
assigns every path below to capsule-engine, capsule-compiler, or capsule-judge
-- none of it belongs in new capsule-ledger commits. The F.3 rule ("nothing
from engine/compiler/judge buckets merges into capsule-ledger") was breached
continuously from 2026-08-26 through 2026-08-31 because nothing enforced it;
this gate is the re-arm.

Deliberately path-only, not file-level, for capsule_ledger/cli/*.py: the
ratified map's own §5 says the final cli/ file-level split (which verb
files wire only the honest-records core vs. which wire a moved bucket) needs
a file-level audit "at execution time, not in this doc-only pass" -- doing
that split here would be guessing. Once the real moves land and the
remaining cli/ surface is known, extend BLOCKED_PREFIXES with the specific
cli/*_cmds.py files that stayed bucket-owned (confirm_cmds.py, judge_cmds.py,
setup_cmds.py, report_cmd.py, enforce_cmds.py, guard_cmds.py, fold_cmds.py,
fold_ref.py, console_cmd.py, tenant_cmds.py, telemetry_cmd.py, lens_cmds.py,
manifest_cmds.py, thresholds_cmds.py, agents_cmd.py, constraints_cmd.py).

Only ADDED or MODIFIED files under a blocked prefix trip the gate --
deletions/renames-away are the eventual move-out PRs this re-extraction
itself will produce, and must stay legal.

Usage: python .github/bucket_scope_gate.py <base-sha> <head-sha>
Exit 0 = clean; 1 = a blocked path grew; 2 = misconfig/usage.
"""
from __future__ import annotations

import subprocess
import sys

# capsule-engine bucket (Amendment F/H §2, §4)
_ENGINE = [
    "capsule_ledger/guards/",
    "capsule_ledger/folds/",
    "capsule_ledger/packs/",
    "capsule_ledger/console/",
    "capsule_ledger/mcp/",
    "capsule_ledger/telemetry/",
    "capsule_ledger/report/",
    "capsule_ledger/lenses/",
    "capsule_ledger/bundle_viewer/",
    "capsule_ledger/registry/",
    "capsule_ledger/policy/",
    "capsule_ledger/tenants.py",
]
# capsule-compiler bucket
_COMPILER = [
    "capsule_ledger/compiler/",
    "capsule_ledger/setup/",
    "capsule_ledger/audit_report/",
]
# capsule-judge bucket (naming decision 2026-08-25/26 + §3.4 ruling)
_JUDGE = [
    "capsule_ledger/judge/",
    "capsule_ledger/confirm/",
]

BLOCKED_PREFIXES = tuple(_ENGINE + _COMPILER + _JUDGE)


def changed_files(base: str, head: str) -> list[tuple[str, str]]:
    out = subprocess.run(
        ["git", "diff", "--name-status", f"{base}...{head}"],
        capture_output=True, text=True, check=True,
    ).stdout
    result = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status, path = parts[0], parts[-1]
        result.append((status, path))
    return result


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: bucket_scope_gate.py <base-sha> <head-sha>", file=sys.stderr)
        return 2
    base, head = argv
    offenders = []
    for status, path in changed_files(base, head):
        if status.startswith("D"):
            continue  # deletions are the move-out this gate exists to allow
        if path.startswith(BLOCKED_PREFIXES):
            offenders.append((status, path))
    if offenders:
        print(
            "F.3 SCOPE VIOLATION: this PR adds/modifies content in a bucket "
            "already assigned to capsule-engine, capsule-compiler, or "
            "capsule-judge by the ratified re-extraction map. Nothing new "
            "may land in these paths in capsule-ledger -- open the PR "
            "against the module's new home instead. Offending files:"
        )
        for status, path in offenders:
            print(f"  {status}\t{path}")
        return 1
    print("OK: no changes to a moved-out bucket path.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
