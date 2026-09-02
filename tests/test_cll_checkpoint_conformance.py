# SPDX-License-Identifier: Apache-2.0
"""Cross-language conformance guard: capsule-ledger checkpoints vs scitt-cose.

The signing body capsule-ledger's ``capsule checkpoint emit`` produces must be
byte-identical to the canonical CLL shape scitt-cose's ``cll.Checkpoint``
parses and verifies -- both are ports of the same ``capsule_emit.checkpoint.
CheckpointRecord.signing_body`` (Amendment E). They diverged once: capsule-
ledger's local ``CheckpointRecord`` shipped an 8-field body with no
``log_id`` while the canonical shape (capsule-emit 0.4.0, scitt-cose 0.2.2)
is 9 fields with ``log_id`` (empty string for single-node). This test is the
guard that stops that recurring: it runs a checkpoint capsule-ledger actually
emitted through scitt-cose's own parser and digest function and demands both
a clean parse and a byte-identical digest.

``scitt-cose`` is not optional here the way it is for
``TestVerifyReceiptOffline`` in ``test_checkpoint.py``: capsule-ledger's own
``dependencies`` require ``capsule-emit[checkpoint]>=0.4.0``, whose
``checkpoint`` extra requires ``scitt-cose>=0.2.0`` -- so any environment that
can import ``capsule_ledger.mmr.checkpoint`` at all already has a real
scitt-cose installed. ``importorskip`` is kept anyway (matching the existing
convention in this test suite) purely as a defensive guard against an
unusual environment, not because the dependency is expected to be absent.
"""
from __future__ import annotations

import secrets
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("scitt_cose")

from scitt_cose.cll import Checkpoint  # noqa: E402


def _emit_capsule_ledger_checkpoint():
    """Emit a real checkpoint via capsule-ledger's own emit path.

    Returns the ``CheckpointRecord`` ``capsule checkpoint emit`` would write
    to disk (before it's serialised to JSON).
    """
    from capsule_emit.checkpoint import MmrLedger

    from capsule_ledger.ledger.capsule import build_event_capsule
    from capsule_ledger.ledger.signing import LocalSigner
    from capsule_ledger.ledger.store import LedgerStore
    from capsule_ledger.mmr.checkpoint import emit_checkpoint

    tmp = Path(tempfile.mkdtemp())
    store = LedgerStore(tmp)
    mmr = MmrLedger(store)
    signer = LocalSigner(key_id="conformance-test-key", secret=secrets.token_bytes(32))

    for i in range(3):
        capsule = build_event_capsule(
            operator="test-op", developer="test-dev", signer=signer,
            event=f"conformance_event_{i}", detail={"i": i},
        )
        mmr.append(capsule, consequential=False)

    cp = emit_checkpoint(mmr, signer, timestamp="2026-08-22T00:00:00Z")
    store.close()
    return cp


def test_legacy_eight_field_checkpoint_fails_scitt_cose():
    """RED: the pre-fix shape (no ``log_id``) is rejected by scitt-cose.

    Reproduces exactly what capsule-ledger emitted before this fix -- the
    real ``to_dict()`` output with the ``log_id`` key stripped back out --
    and demands scitt-cose's parser refuse it. If this assertion ever starts
    failing, ``Checkpoint.from_dict`` stopped requiring ``log_id`` and this
    guard has lost its ability to catch the regression it exists for.
    """
    legacy_dict = _emit_capsule_ledger_checkpoint().to_dict()
    del legacy_dict["log_id"]

    with pytest.raises(KeyError, match="log_id"):
        Checkpoint.from_dict(legacy_dict)


def test_capsule_ledger_checkpoint_verifies_green():
    """GREEN: today's capsule-ledger checkpoint parses AND digest-matches.

    A clean parse alone would not be enough -- a parser that silently
    defaulted ``log_id`` would also "pass" while producing a different
    digest, breaking every downstream TS registration. This demands the
    digest scitt-cose independently recomputes from the canonical JSON is
    byte-identical to the one capsule-ledger signed.
    """
    ledger_cp = _emit_capsule_ledger_checkpoint()

    scitt_cp = Checkpoint.from_dict(ledger_cp.to_dict())

    assert scitt_cp.digest() == ledger_cp.digest(), (
        f"digest mismatch: capsule-ledger computed {ledger_cp.digest()!r}, "
        f"scitt-cose independently recomputed {scitt_cp.digest()!r} -- "
        "the signing-body canonicalization has diverged again"
    )
