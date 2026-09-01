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
fold_ref.py, tenant_cmds.py, lens_cmds.py, manifest_cmds.py,
thresholds_cmds.py, agents_cmd.py, constraints_cmd.py). console_cmd.py was
deleted outright and telemetry_cmd.py turned out to be core (see the RESIDUALS
correction below), so both are off this candidate list now.

Only ADDED or MODIFIED files under a blocked prefix trip the gate --
deletions/renames-away are the eventual move-out PRs this re-extraction
itself will produce, and must stay legal.

**[ldg-endgame-bucket-deletion] reclassification, ratified:** executing the
bucket-cluster deletion (packs/compiler/judge/setup/audit_report/tenants.py)
surfaced hard, non-optional dependencies from surviving F.1-core code onto
three of the paths this map calls "engine bucket" -- with packs/compiler/
judge/setup now gone, re-importing capsule-engine or duplicating code is not
an option, so these three are core, not engine-destined, and are removed from
_ENGINE below:
  - ``guards/`` (minus the now-deleted ``tool_call.py``) -- ``holds/``
    (F.1 core) calls into it directly.
  - ``policy/`` -- ``policy/resolve.py`` is ``holds/policy.py``'s manifest
    resolver, and ``policy/loader.py``/``catalog_defs/`` back the shared
    ``tests/conftest.py`` fixtures every ``holds/`` test uses.
  - ``folds/`` -- the still-live, still-registered ``capsule fold`` CLI verb
    (fold_cmds.py) owns this outright; it was never engine-only.

**CORRECTION (2026-09-01, [ldg-ledger-scope-re-extraction] RESIDUALS pass) --
the ``report/`` row of the reclassification above was wrong, kept here (not
deleted) so the reasoning chain stays auditable:** the original claim was
that ``bundle_viewer/base_viewer.py`` "backs the still-live ``capsule bundle
--with-viewer``" and hard-imports ``report.render.encode_fragment``, making
``report/`` an undeletable core dependency. Traced at execution time instead
of taken on faith: ``--with-viewer`` (``cli/bundle_cmd.py``) only ever calls
``bundle_viewer.viewer.render_offline_viewer_html`` -- the byte-for-byte
scitt-cose vendor copy -- never ``base_viewer.py``. ``base_viewer.py`` is a
separate, newer plug-in seam (PR #104) reachable only via
``bundle_viewer/__init__.py``'s re-export, with zero real CLI callers.
Both ``base_viewer.py`` (+ its two static JS files) and ``report/`` moved to
capsule-engine in this pass -- ``report/``'s capsule-engine copy was
independently confirmed to already be the current, richer version, wired
into its own live ``capsule guard dry-run --share`` via ``guard_cmds.py``,
with replay_command/tuning-box/enforce-band chrome capsule-ledger's copy
never had. ``report/`` is restored to _ENGINE below. ``bundle_viewer/``
itself is REMOVED from _ENGINE: ``viewer.py``/``offline_shell.html`` (the
actual ``--with-viewer`` backing) are genuinely core and must stay
modifiable here; only ``base_viewer.py`` and its two static JS files moved.

**CORRECTION (2026-09-01, [ldg-ledger-scope-re-extraction] RESIDUALS pass
§3.1):** ``registry/`` is NOT a blanket engine-bucket directory -- per
Steven's ruling, capsule-ledger keeps a minimal, self-contained
``describe_action_class`` shim (its own tiny embedded label data, no
capsule-engine import) for its core read/verify display surface
(``cli/format.py``); only the full vendored CPB registry (``cpb_registry.json``
+ the ``provisional_field_conventions`` half of ``conventions.json``) moved to
capsule-engine as the interim vendor-of-record. _ENGINE below narrows from
the whole ``registry/`` directory to the one file that's actually gone.

``mcp/`` was deleted outright in an earlier RESIDUALS-pass PR (capsule-engine
already carried a current, self-sufficient copy); its _ENGINE entry stays as
a guard against anything new landing back under that path.

**CORRECTION (2026-09-01, [ldg-ledger-scope-re-extraction] RESIDUALS pass,
console/telemetry trace):** traced, not assumed, per the ratified map's own
"trace core dependents before moving" rule. ``console/`` has exactly one
importer repo-wide -- ``cli/console_cmd.py`` -- which nothing else in core
calls; capsule-engine already carries a byte-identical copy of both
(confirmed via diff, only the intra-package imports differ, rewritten for
the installed-package form), so both are deleted outright here, the same
disposition as ``mcp/``. ``console/``'s _ENGINE entry stays, for the same
reason ``mcp/``'s does: a guard against anything new landing back under a
path this repo no longer owns.

``telemetry/`` is the opposite finding: ``cli/main.py`` (``record_install_seen``)
and the core evidence verbs ``cli/bundle_cmd.py``, ``cli/verify_cmd.py``,
``cli/show_cmd.py`` (all three via ``record_evidence_touch``) hard-import
``telemetry.record`` unconditionally, at the top of ``run()`` -- not behind a
flag, not optional. capsule-ledger cannot import capsule-engine to satisfy
this (the dependency runs the other way), so ``telemetry/`` cannot move
without breaking core. It is core, not engine-destined, for the same reason
``guards/``/``policy/``/``folds/``/``report/`` are -- removed from _ENGINE
below. ``telemetry_cmd.py`` (the ``capsule telemetry status/funnel`` verb)
was never a separate question once its underlying package is core.

Usage: python .github/bucket_scope_gate.py <base-sha> <head-sha>
Exit 0 = clean; 1 = a blocked path grew; 2 = misconfig/usage.
"""
from __future__ import annotations

import subprocess
import sys

# capsule-engine bucket (Amendment F/H §2, §4). guards/, policy/, folds/
# stay core -- see the reclassification note above. report/ is back (2026-09-01
# correction, see above); bundle_viewer/ is narrowed to base_viewer.py + its
# static JS specifically, not the whole directory -- viewer.py/offline_shell.html
# are core and must stay modifiable here. registry/ is narrowed the same way
# to just cpb_registry.json -- the describe_action_class shim stays core.
# telemetry/ is also core now (see the console/telemetry trace correction
# above) and removed from this list; console/ was deleted outright and its
# entry stays only as a re-add guard.
_ENGINE = [
    "capsule_ledger/packs/",
    "capsule_ledger/console/",
    "capsule_ledger/mcp/",
    "capsule_ledger/lenses/",
    "capsule_ledger/report/",
    "capsule_ledger/tenants.py",
    # File-level, not directory-level: bundle_viewer/viewer.py +
    # static/offline_shell.html (the actual `--with-viewer` backing) are
    # core and must stay modifiable here. Only the plug-in seam moved.
    "capsule_ledger/bundle_viewer/base_viewer.py",
    "capsule_ledger/bundle_viewer/static/capsule_viewer.js",
    "capsule_ledger/bundle_viewer/static/conversation_exchange_card.js",
    # File-level, not directory-level (2026-09-01 correction, see above):
    # registry/ itself stays core (a minimal shim); only the full vendored
    # CPB table moved.
    "capsule_ledger/registry/cpb_registry.json",
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
