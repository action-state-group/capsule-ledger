# SPDX-License-Identifier: Apache-2.0
"""``[ldg-live-compile-demo]``: the on-stage payload -- one statement in
English compiles, live, into **P** (a wicket config checked at act time)
and **F** (a fold evaluated at report time), sealed together as the
**compilation record C**. Then the declaration is edited and recompiled,
and both artifacts move together -- the drift check is the point: P and F
cannot diverge, and C is what proves it.

Run as ``python -m capsule_ledger.examples.live_compile_demo.demo``.

**Why the edit narrows ``action_class``, not the window.** The design draft
for this demo offered two example edits -- "tighten a window" or "add an
option-count minimum." Both were checked empirically before writing this
module: ``Declaration.window`` only reaches the forward compile
(``PlanDefinition.window``) -- ``_fold_for_declaration`` never reads it, so
a window-only edit moves P while F stays byte-identical, which is the
opposite of the point being made on stage. An option-count-minimum
precondition does not exist in the closed v0 precondition vocabulary
(``compiler/precondition.py``'s six primitives) -- adding one is a new
primitive with its own conformance vectors, out of scope here.
``action_class`` narrowing is the edit that is actually true today: it
moves P (``allowed_actions``) and F (the fold's ``action_class`` filter,
via ``binding`` -- see ``setup/compile_bridge.py``'s
``attainment_declaration_for``, fixed alongside this module so that filter
is reachable at all) together, with zero new vocabulary.

Nothing here is model-assisted -- both compiles are the same deterministic
``compile_declaration`` the rest of the compiler stack uses (design §2.1,
build plan Phase 2 item 1). The live model call in this demo's sequence is
``capsule setup propose`` (see ``[ldg-live-compile-demo]``'s outbox entry
for what is and is not wired up yet); this module is the payload that
follows it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from capsule_ledger.compiler.compile import (
    CompiledDeclaration,
    compile_declaration,
    seal_compilation_record,
    verify_compilation_record,
    wicket_entry_for,
)
from capsule_ledger.guards.signing import LocalSigner
from capsule_ledger.ledger import LedgerStore
from capsule_ledger.setup.candidates import AttainmentCandidate
from capsule_ledger.setup.compile_bridge import attainment_declaration_for
from capsule_ledger.setup.declarations import candidate_digest

__all__ = ["LiveCompileResult", "run"]

OPERATOR = "demo-operator"
DEVELOPER = "demo-presenter@v1"
SIGNER = LocalSigner(key_id="live-compile-demo-key", secret=hashlib.sha256(b"ldg-live-compile-demo").digest())

# Step 1 -- the statement spoken in English, before anyone touches a keyboard:
# "a remediation action was confirmed by an external system."
INITIAL = AttainmentCandidate(
    outcome_id="workforce.remediation_confirmed/1.0.0",
    statement="A remediation action was confirmed by an external system.",
    action_class="remediation",
)

# Step 2 -- the live edit: narrow which action satisfies the outcome.
EDITED = AttainmentCandidate(
    outcome_id="workforce.remediation_confirmed/1.0.0",
    statement="A tier-2 remediation action was confirmed by an external system.",
    action_class="remediation.tier2",
)


@dataclass(frozen=True)
class LiveCompileResult:
    initial_compiled: CompiledDeclaration
    initial_capsule: dict
    edited_compiled: CompiledDeclaration
    edited_capsule: dict
    clean_drift: object  # DriftResult -- re-deriving C1 from D1 must be clean
    caught_drift: object  # DriftResult -- claiming C1 against D2 must be caught


def _seal(candidate: AttainmentCandidate, *, d_prev_digest: str | None, ledger: LedgerStore) -> tuple[CompiledDeclaration, dict]:
    declaration = attainment_declaration_for(candidate)
    compiled = compile_declaration(declaration)
    d_digest = candidate_digest(candidate)
    capsule = seal_compilation_record(
        compiled,
        d_digest=d_digest,
        operator=OPERATOR,
        developer=DEVELOPER,
        signer=SIGNER,
        d_prev_digest=d_prev_digest,
    )
    ledger.append(capsule, consequential=False)
    return compiled, capsule


def _print_header(title: str) -> None:
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")


def _print_compiled(label: str, candidate: AttainmentCandidate, compiled: CompiledDeclaration) -> None:
    print(f"\n-- {label} --")
    print(f'statement (English): "{candidate.statement}"')
    print(f"forward verdict: {compiled.forward.verdict}")
    print("P (wicket config, checked at act time):")
    wicket = wicket_entry_for(compiled.forward.plan, wicket_id=f"{candidate.outcome_id}/wicket")
    print(json.dumps(wicket.config, indent=2, sort_keys=True))
    print(f"P digest: {compiled.forward.digest()}")
    print(f"backward verdict: {compiled.backward.verdict}")
    print("F (fold, evaluated at report time):")
    print(json.dumps(compiled.backward.fold.canonical_dict(), indent=2, sort_keys=True))
    print(f"F digest: {compiled.backward.digest()}")


def _print_capsule(label: str, capsule: dict) -> None:
    detail = capsule["asg_payload"]["detail"]
    print(f"\n-- {label} (compilation record C) --")
    print(f"capsule_id: {capsule['capsule_id']}")
    print(json.dumps(detail, indent=2, sort_keys=True))


def run(store_dir: str | Path) -> LiveCompileResult:
    with LedgerStore(store_dir) as ledger:
        _print_header("STEP 1 -- compile the declaration, in both directions")
        initial_compiled, initial_capsule = _seal(INITIAL, d_prev_digest=None, ledger=ledger)
        _print_compiled("D1 (as declared)", INITIAL, initial_compiled)
        _print_capsule("C1", initial_capsule)

        _print_header("STEP 2 -- edit the declaration and recompile")
        d1_digest = candidate_digest(INITIAL)
        edited_compiled, edited_capsule = _seal(EDITED, d_prev_digest=d1_digest, ledger=ledger)
        _print_compiled("D2 (edited: action_class narrowed to remediation.tier2)", EDITED, edited_compiled)
        _print_capsule("C2", edited_capsule)

        print("\n-- both halves moved together --")
        print(f"P changed: {initial_compiled.forward.digest() != edited_compiled.forward.digest()}")
        print(f"F changed: {initial_compiled.backward.digest() != edited_compiled.backward.digest()}")

        _print_header("STEP 3 -- the drift check: re-derive, don't trust")
        clean = verify_compilation_record(
            initial_capsule["asg_payload"]["detail"],
            recompiled=compile_declaration(attainment_declaration_for(INITIAL)),
            d_digest=d1_digest,
        )
        print(f"\nre-deriving C1 from D1 fresh: drifted={clean.drifted} (expected: False -- nothing changed)")

        caught = verify_compilation_record(
            initial_capsule["asg_payload"]["detail"],
            recompiled=edited_compiled,
            d_digest=d1_digest,
        )
        print(
            f"presenting C1 against the EDITED compile: drifted={caught.drifted}, "
            f"p_drifted={caught.p_drifted}, f_drifted={caught.f_drifted} "
            "(expected: all True -- a stale or tampered C is caught, not trusted)"
        )
        if not (caught.drifted and caught.p_drifted and caught.f_drifted):
            print("DRIFT CHECK DID NOT CATCH THE MUTANT -- STOP, do not run this on stage.", file=sys.stderr)
            raise SystemExit(1)

        return LiveCompileResult(
            initial_compiled=initial_compiled,
            initial_capsule=initial_capsule,
            edited_compiled=edited_compiled,
            edited_capsule=edited_capsule,
            clean_drift=clean,
            caught_drift=caught,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default=None, help="ledger directory to write (default: a fresh temp dir)")
    args = parser.parse_args(argv)

    if args.out_dir:
        store_dir = Path(args.out_dir)
        store_dir.mkdir(parents=True, exist_ok=True)
    else:
        import tempfile

        store_dir = Path(tempfile.mkdtemp(prefix="live-compile-demo-"))

    run(store_dir)
    print(f"\nledger written to: {store_dir}")
    print(f"$CAP report --ledger {store_dir}")
    print(f"$CAP bundle --ledger {store_dir} --out {store_dir}/bundle.json --with-viewer")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
