# SPDX-License-Identifier: Apache-2.0
"""``setup.compile_bridge.attainment_declaration_for`` (``[ldg-live-compile-demo]``):
the fix that makes an attainment candidate's ``action_class`` actually
reach the fold. Before this fix, ``_fold_for_declaration`` read
``d.binding.get("action_class")`` -- real, already-wired logic -- but
``attainment_declaration_for`` never populated ``binding`` at all, so P
moved on an ``action_class`` edit while F silently stayed put: exactly the
kind of forward/backward drift the compilation record C exists to make
visible, invisible because F never varied to begin with.

This is the same falsification shape as ``test_compiler_compile.py``'s
required mutant: edit D, recompile, and prove **both** halves move --
if F stays fixed while D changes, C is decoration for that edit.
"""
from __future__ import annotations

import hashlib

from capsule_ledger.compiler.compile import (
    compile_declaration,
    seal_compilation_record,
    verify_compilation_record,
)
from capsule_ledger.setup.candidates import AttainmentCandidate
from capsule_ledger.setup.compile_bridge import attainment_declaration_for

OPERATOR = "test-operator"
DEVELOPER = "test-developer@v1"


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _candidate(action_class: str) -> AttainmentCandidate:
    return AttainmentCandidate(
        outcome_id="outcome.remediation_confirmed",
        statement="a remediation action was confirmed by an external system",
        action_class=action_class,
    )


def test_attainment_declaration_for_carries_action_class_into_binding():
    d = attainment_declaration_for(_candidate("remediation"))
    assert d.binding == {"action_class": "remediation"}


def test_narrowing_action_class_moves_both_p_and_f():
    """The exact drift-check edit the live demo performs on stage: narrow
    ``action_class``, recompile, and both P and F must move -- not just P."""
    wide = compile_declaration(attainment_declaration_for(_candidate("remediation")))
    narrow = compile_declaration(attainment_declaration_for(_candidate("remediation.tier2")))

    assert wide.forward.digest() != narrow.forward.digest()
    assert wide.backward.digest() != narrow.backward.digest()


def test_falsification_action_class_edit_is_caught_by_verify_compilation_record(signer):
    """THE required falsification test for this fix: seal C against the
    wide candidate, then present the narrowed recompile as if it were the
    same D. verify_compilation_record must flag both halves drifted -- if
    f_drifted stays False here, F never actually moved and C would be
    silently vouching for a fold that no longer matches what was sealed."""
    wide = compile_declaration(attainment_declaration_for(_candidate("remediation")))
    d_digest = _digest("D-wide")
    cap = seal_compilation_record(wide, d_digest=d_digest, operator=OPERATOR, developer=DEVELOPER, signer=signer)
    detail = cap["asg_payload"]["detail"]

    narrow = compile_declaration(attainment_declaration_for(_candidate("remediation.tier2")))
    drift = verify_compilation_record(detail, recompiled=narrow, d_digest=d_digest)

    assert drift.drifted is True
    assert drift.p_drifted is True
    assert drift.f_drifted is True


def test_falsification_mutant_is_provably_not_a_vacuous_pass(signer):
    # Proves the drift check above is a real check, not one that always
    # reports True: sealing and re-verifying the SAME candidate must come
    # back clean on both halves.
    wide = compile_declaration(attainment_declaration_for(_candidate("remediation")))
    d_digest = _digest("D-wide")
    cap = seal_compilation_record(wide, d_digest=d_digest, operator=OPERATOR, developer=DEVELOPER, signer=signer)
    detail = cap["asg_payload"]["detail"]

    clean = verify_compilation_record(
        detail, recompiled=compile_declaration(attainment_declaration_for(_candidate("remediation"))), d_digest=d_digest
    )
    assert clean.drifted is False
    assert clean.p_drifted is False
    assert clean.f_drifted is False
