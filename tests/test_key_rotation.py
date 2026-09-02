# SPDX-License-Identifier: Apache-2.0
"""Key rotation as a recorded ledger event, plus time-fenced revocation:
a revoked key's signature is trusted for records dated at-or-before its
revocation timestamp, and rejected for anything claiming to postdate it
(gating §2 parking lot)."""
from __future__ import annotations

from capsule_ledger.guards.capsule import build_event_capsule
from cll.revocation import (
    ROTATION_EVENT,
    build_key_timeline,
    check_time_fenced_revocation,
)

from capsule_ledger.cli.main import main
from capsule_ledger.ledger import LedgerStore
from capsule_ledger.ledger.signing import LocalSigner, key_fingerprint

OLD_KEY_ID = "key-2026-q1"
OLD_SECRET = b"old-secret-material"
NEW_KEY_ID = "key-2026-q2"
NEW_SECRET = b"new-secret-material"
ROTATED_AT = "2026-04-01T00:00:00Z"


def _rotation_detail(*, rotated_at: str = ROTATED_AT) -> dict:
    return {
        "old_key_id": OLD_KEY_ID,
        "old_key_fingerprint": key_fingerprint(OLD_KEY_ID, OLD_SECRET),
        "new_key_id": NEW_KEY_ID,
        "new_key_fingerprint": key_fingerprint(NEW_KEY_ID, NEW_SECRET),
        "rotated_at": rotated_at,
    }


def _append_rotation_event(store: LedgerStore, *, rotated_at: str = ROTATED_AT) -> dict:
    old_signer = LocalSigner(key_id=OLD_KEY_ID, secret=OLD_SECRET)
    capsule = build_event_capsule(
        operator="acme",
        developer="key-admin",
        signer=old_signer,
        event=ROTATION_EVENT,
        detail=_rotation_detail(rotated_at=rotated_at),
        timestamp=rotated_at,
    )
    store.append(capsule, consequential=True)
    return capsule


def _signed_record(*, key_id: str, secret: bytes, timestamp: str, event: str = "note") -> dict:
    signer = LocalSigner(key_id=key_id, secret=secret)
    return build_event_capsule(
        operator="acme", developer="agent@v1", signer=signer, event=event, detail={}, timestamp=timestamp
    )


# -- unit: fingerprints + timeline reconstruction -----------------------------


def test_key_fingerprint_is_stable_and_key_id_bound():
    fp1 = key_fingerprint("k1", b"secret")
    fp2 = key_fingerprint("k1", b"secret")
    fp3 = key_fingerprint("k2", b"secret")
    assert fp1 == fp2
    assert fp1 != fp3  # same secret, different key_id -> different fingerprint
    assert len(fp1) == 64  # sha256 hex


def test_build_key_timeline_reconstructs_from_ledger_alone(store):
    _append_rotation_event(store)
    timeline = build_key_timeline(store)

    assert timeline[OLD_KEY_ID].revoked_at == ROTATED_AT
    assert timeline[NEW_KEY_ID].activated_at == ROTATED_AT
    assert timeline[NEW_KEY_ID].revoked_at is None  # still live


def test_build_key_timeline_chains_across_multiple_rotations(store):
    _append_rotation_event(store, rotated_at="2026-01-01T00:00:00Z")
    third_signer_detail = {
        "old_key_id": NEW_KEY_ID,
        "old_key_fingerprint": key_fingerprint(NEW_KEY_ID, NEW_SECRET),
        "new_key_id": "key-2026-q3",
        "new_key_fingerprint": key_fingerprint("key-2026-q3", b"third-secret"),
        "rotated_at": "2026-07-01T00:00:00Z",
    }
    signer = LocalSigner(key_id=NEW_KEY_ID, secret=NEW_SECRET)
    capsule = build_event_capsule(
        operator="acme", developer="key-admin", signer=signer, event=ROTATION_EVENT,
        detail=third_signer_detail, timestamp="2026-07-01T00:00:00Z",
    )
    store.append(capsule, consequential=True)

    timeline = build_key_timeline(store)
    assert timeline[OLD_KEY_ID].revoked_at == "2026-01-01T00:00:00Z"
    assert timeline[NEW_KEY_ID].activated_at == "2026-01-01T00:00:00Z"
    assert timeline[NEW_KEY_ID].revoked_at == "2026-07-01T00:00:00Z"
    assert timeline["key-2026-q3"].activated_at == "2026-07-01T00:00:00Z"
    assert timeline["key-2026-q3"].revoked_at is None


# -- the core time-fenced revocation property ---------------------------------


def test_time_fenced_revocation_accepts_record_dated_before_rotation():
    timeline = build_key_timeline_from_capsules([_rotation_capsule()])
    before = _signed_record(key_id=OLD_KEY_ID, secret=OLD_SECRET, timestamp="2026-03-01T00:00:00Z")
    finding = check_time_fenced_revocation(before, timeline)
    assert finding.ok is True


def test_time_fenced_revocation_rejects_record_dated_after_rotation():
    timeline = build_key_timeline_from_capsules([_rotation_capsule()])
    after = _signed_record(key_id=OLD_KEY_ID, secret=OLD_SECRET, timestamp="2026-05-01T00:00:00Z")
    finding = check_time_fenced_revocation(after, timeline)
    assert finding.ok is False
    assert "revoked" in finding.reason
    assert OLD_KEY_ID in finding.reason


def test_time_fenced_revocation_accepts_rotation_event_at_the_boundary_instant():
    """The rotation event itself, signed by the outgoing key at exactly its
    own revocation timestamp, must stay valid -- otherwise the rotation
    record could never verify, contradicting the "real, verifiable record"
    requirement."""
    rotation_capsule = _rotation_capsule()
    timeline = build_key_timeline_from_capsules([rotation_capsule])
    finding = check_time_fenced_revocation(rotation_capsule, timeline)
    assert finding.ok is True


def test_time_fenced_revocation_new_key_unaffected_by_old_keys_fence():
    timeline = build_key_timeline_from_capsules([_rotation_capsule()])
    new_key_record = _signed_record(key_id=NEW_KEY_ID, secret=NEW_SECRET, timestamp="2026-12-01T00:00:00Z")
    finding = check_time_fenced_revocation(new_key_record, timeline)
    assert finding.ok is True


def test_time_fenced_revocation_ignores_key_with_no_rotation_history():
    finding = check_time_fenced_revocation(
        _signed_record(key_id="never-rotated", secret=b"x", timestamp="2026-01-01T00:00:00Z"), {}
    )
    assert finding.ok is True


def _rotation_capsule() -> dict:
    old_signer = LocalSigner(key_id=OLD_KEY_ID, secret=OLD_SECRET)
    return build_event_capsule(
        operator="acme", developer="key-admin", signer=old_signer, event=ROTATION_EVENT,
        detail=_rotation_detail(), timestamp=ROTATED_AT,
    )


class _FakeLedger:
    """A minimal LedgerAPI-shaped stand-in exposing only ``scan()`` --
    ``build_key_timeline`` never needs more than that."""

    def __init__(self, capsules: list[dict]):
        self._capsules = capsules

    def scan(self, query=None):
        from capsule_ledger.ledger.records import LedgerRecord

        for i, capsule in enumerate(self._capsules, start=1):
            yield LedgerRecord(seq=i, capsule_id=capsule["capsule_id"], capsule=capsule, segment="mem", consequential=True)


def build_key_timeline_from_capsules(capsules: list[dict]) -> dict:
    return build_key_timeline(_FakeLedger(capsules))


# -- integration: LedgerStore.verify() enforces the fence ---------------------


def test_store_verify_accepts_pre_revocation_record(store):
    _append_rotation_event(store)
    before = _signed_record(key_id=OLD_KEY_ID, secret=OLD_SECRET, timestamp="2026-03-01T00:00:00Z")
    record = store.append(before, consequential=True)

    result = store.verify(record.capsule_id)
    assert result.ok is True


def test_store_verify_rejects_post_revocation_record_signed_by_old_key(store):
    _append_rotation_event(store)
    after = _signed_record(key_id=OLD_KEY_ID, secret=OLD_SECRET, timestamp="2026-05-01T00:00:00Z")
    record = store.append(after, consequential=True)

    result = store.verify(record.capsule_id)
    assert result.ok is False
    assert any(f.code == "key_revoked_at_timestamp" for f in result.findings)


def test_store_verify_accepts_post_revocation_record_signed_by_new_key(store):
    _append_rotation_event(store)
    after = _signed_record(key_id=NEW_KEY_ID, secret=NEW_SECRET, timestamp="2026-05-01T00:00:00Z")
    record = store.append(after, consequential=True)

    result = store.verify(record.capsule_id)
    assert result.ok is True


# -- CLI: `capsule key rotate` / `capsule key status` --------------------------


def test_cli_key_rotate_appends_a_verifiable_capsule(tmp_path, capsys):
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()

    rc = main([
        "key", "rotate", "--ledger", str(ledger_dir),
        "--old-key-id", OLD_KEY_ID, "--old-secret", OLD_SECRET.decode(),
        "--new-key-id", NEW_KEY_ID, "--new-secret", NEW_SECRET.decode(),
        "--operator", "acme", "--developer", "key-admin", "--reason", "scheduled rotation",
        "--at", ROTATED_AT,
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert f"rotated: {OLD_KEY_ID} -> {NEW_KEY_ID} at {ROTATED_AT}" in out
    assert "recorded as " in out
    capsule_id = [line for line in out.splitlines() if line.startswith("recorded as ")][0].split()[-1]

    rc = main(["verify", capsule_id, "--ledger", str(ledger_dir)])
    assert rc == 0
    out = capsys.readouterr().out
    assert f"✓ verifies · {capsule_id}" in out

    store = LedgerStore(ledger_dir)
    record = store.fetch(capsule_id)
    assert record.capsule["asg_payload"]["event"] == ROTATION_EVENT
    detail = record.capsule["asg_payload"]["detail"]
    assert detail["old_key_id"] == OLD_KEY_ID
    assert detail["new_key_id"] == NEW_KEY_ID
    assert detail["old_key_fingerprint"] == key_fingerprint(OLD_KEY_ID, OLD_SECRET)
    assert detail["new_key_fingerprint"] == key_fingerprint(NEW_KEY_ID, NEW_SECRET)
    assert detail["reason"] == "scheduled rotation"
    store.close()


def test_cli_key_rotate_generates_a_secret_when_none_given(tmp_path, capsys):
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()

    rc = main([
        "key", "rotate", "--ledger", str(ledger_dir),
        "--old-key-id", OLD_KEY_ID, "--old-secret", OLD_SECRET.decode(),
        "--new-key-id", NEW_KEY_ID,
        "--operator", "acme", "--developer", "key-admin",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "new signing secret (shown once" in out
    assert f"export CAPSULE_MCP_SIGNING_KEY_ID={NEW_KEY_ID}" in out


def test_cli_key_rotate_requires_old_key_material(tmp_path, capsys):
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    rc = main(["key", "rotate", "--ledger", str(ledger_dir), "--new-key-id", NEW_KEY_ID,
               "--operator", "acme", "--developer", "key-admin"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "--old-key-id/--old-secret are required" in err


def test_cli_key_rotate_rejects_same_old_and_new_key_id(tmp_path, capsys):
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    rc = main([
        "key", "rotate", "--ledger", str(ledger_dir),
        "--old-key-id", OLD_KEY_ID, "--old-secret", OLD_SECRET.decode(),
        "--new-key-id", OLD_KEY_ID, "--operator", "acme", "--developer", "key-admin",
    ])
    assert rc == 2
    err = capsys.readouterr().err
    assert "must differ" in err


def test_cli_key_status_prints_timeline(tmp_path, capsys):
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    store = LedgerStore(ledger_dir)
    _append_rotation_event(store)
    store.close()

    rc = main(["key", "status", "--ledger", str(ledger_dir)])
    assert rc == 0
    out = capsys.readouterr().out
    assert f"{OLD_KEY_ID}\tactivated (unrecorded)\trevoked at {ROTATED_AT}" in out
    assert f"{NEW_KEY_ID}\tactivated {ROTATED_AT}\tlive" in out


def test_cli_key_status_on_ledger_with_no_rotations(tmp_path, capsys):
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    store = LedgerStore(ledger_dir)
    store.close()

    rc = main(["key", "status", "--ledger", str(ledger_dir)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "no key_rotation events recorded" in out


def test_cli_verify_catches_a_time_fenced_revocation_violation(tmp_path, capsys):
    """End-to-end: `capsule key rotate` records the rotation, a record dated
    after it and signed by the outgoing key is appended directly, and
    `capsule verify` must reject it -- exit 1, not a silent pass."""
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()

    rc = main([
        "key", "rotate", "--ledger", str(ledger_dir),
        "--old-key-id", OLD_KEY_ID, "--old-secret", OLD_SECRET.decode(),
        "--new-key-id", NEW_KEY_ID, "--new-secret", NEW_SECRET.decode(),
        "--operator", "acme", "--developer", "key-admin", "--at", ROTATED_AT,
    ])
    assert rc == 0
    capsys.readouterr()

    store = LedgerStore(ledger_dir)
    after = _signed_record(key_id=OLD_KEY_ID, secret=OLD_SECRET, timestamp="2026-05-01T00:00:00Z")
    record = store.append(after, consequential=True)
    store.close()

    rc = main(["verify", record.capsule_id, "--ledger", str(ledger_dir)])
    assert rc == 1
    out = capsys.readouterr().out
    assert f"✗ verification failed · {record.capsule_id}" in out
    assert "key_revoked_at_timestamp" in out
