# SPDX-License-Identifier: Apache-2.0
"""`capsule init --pack <name>`: install a starter pack in observe mode --
materializes .capsule/{catalog,policy} under a project dir, and optionally
records a signed activation capsule when --ledger is given."""
from __future__ import annotations

from pathlib import Path

from capsule_ledger.cli.main import main
from capsule_ledger.ledger import LedgerStore
from capsule_ledger.policy import load_manifest_file


def test_init_installs_payments_safety_pack(tmp_path, capsys):
    rc = main(["init", "--pack", "payments-safety", "--project-dir", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "asg/payments-safety/1.0.0" in out
    assert "observe mode" in out

    manifest_path = tmp_path / ".capsule" / "policy" / "manifest.yaml"
    assert manifest_path.is_file()
    manifest = load_manifest_file(manifest_path)
    assert len(manifest.packs) == 1
    assert manifest.packs[0].pack_id == "asg/payments-safety/1.0.0"
    assert manifest.packs[0].mode == "observe"

    assert any((tmp_path / ".capsule" / "catalog" / "folds").glob("payments_safety.*.yaml"))
    assert len(list((tmp_path / ".capsule" / "catalog" / "wickets").glob("payments_safety.*.yaml"))) == 3


def test_init_unknown_pack_lists_available(tmp_path, capsys):
    rc = main(["init", "--pack", "does-not-exist", "--project-dir", str(tmp_path)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "payments-safety" in err  # the one real pack is listed as a hint


def test_init_records_activation_capsule_when_ledger_given(tmp_path, capsys):
    ledger_dir = tmp_path / "ledger"
    rc = main(
        [
            "init",
            "--pack",
            "payments-safety",
            "--project-dir",
            str(tmp_path),
            "--ledger",
            str(ledger_dir),
            "--operator",
            "acme-checkout",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "activation recorded:" in out

    store = LedgerStore(ledger_dir)
    try:
        records = list(store.scan())
    finally:
        store.close()
    assert len(records) == 1
    payload = records[0].capsule["asg_payload"]
    assert payload["event"] == "policy_manifest_activated"
    packs_detail = payload["detail"]["packs"]
    assert len(packs_detail) == 1
    assert packs_detail[0]["pack_id"] == "asg/payments-safety/1.0.0"
    assert packs_detail[0]["mode"] == "observe"
    assert len(packs_detail[0]["digest"]) == 64


def test_init_without_ledger_writes_manifest_only(tmp_path, capsys):
    rc = main(["init", "--pack", "payments-safety", "--project-dir", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "no activation capsule recorded" in out


PAYMENTS_SAFETY_DIR = Path(__file__).parent.parent / "capsule_ledger" / "packs" / "catalog" / "payments-safety"


def _real_pins_for(pack_dir) -> dict:
    from capsule_ledger.packs.loader import load_pack_dir

    pack = load_pack_dir(pack_dir)
    pins = {pack.pack_id: pack.definition_digest()}
    for fold in pack.folds:
        pins[fold.fold_id] = fold.definition_digest()
    return pins


def _write_pins(tmp_path, pins: dict):
    import yaml

    path = tmp_path / "pins.yaml"
    path.write_text(yaml.safe_dump(pins))
    return path


def test_init_with_correct_pins_installs(tmp_path, capsys):
    pins_path = _write_pins(tmp_path, _real_pins_for(PAYMENTS_SAFETY_DIR))
    rc = main(
        ["init", "--pack", "payments-safety", "--project-dir", str(tmp_path / "proj"), "--pins", str(pins_path)]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "registry-pin verification passed" in out
    assert (tmp_path / "proj" / ".capsule" / "policy" / "manifest.yaml").is_file()


def test_init_with_mismatched_pin_fails_closed_and_installs_nothing(tmp_path, capsys):
    pins = _real_pins_for(PAYMENTS_SAFETY_DIR)
    pack_id = next(k for k in pins if k.startswith("asg/"))
    pins[pack_id] = "f" * 64
    pins_path = _write_pins(tmp_path, pins)

    project_dir = tmp_path / "proj"
    rc = main(["init", "--pack", "payments-safety", "--project-dir", str(project_dir), "--pins", str(pins_path)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "pin_digest_mismatch" in err
    assert not project_dir.exists()


def test_init_with_missing_pin_fails_closed(tmp_path, capsys):
    pins_path = _write_pins(tmp_path, {"some-other/pack/1.0.0": "a" * 64})
    project_dir = tmp_path / "proj"
    rc = main(["init", "--pack", "payments-safety", "--project-dir", str(project_dir), "--pins", str(pins_path)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "pin_not_found" in err
    assert not project_dir.exists()


def test_init_without_pins_prints_seedable_digests(tmp_path, capsys):
    rc = main(["init", "--pack", "payments-safety", "--project-dir", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "seed a pins file" in out
    assert "asg/payments-safety/1.0.0:" in out
