# SPDX-License-Identifier: Apache-2.0
"""`capsule init --pack <name>`: install a starter pack in observe mode --
materializes .capsule/{catalog,policy} under a project dir, and optionally
records a signed activation capsule when --ledger is given."""
from __future__ import annotations

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
