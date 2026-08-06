# SPDX-License-Identifier: Apache-2.0
"""`capsule manifest show|activate|verify` golden-output tests."""
from __future__ import annotations

import shutil
from pathlib import Path

from asg_ledger.cli.main import main
from asg_ledger.guards import Action, GuardEngine, LocalSigner
from asg_ledger.ledger import LedgerStore
from asg_ledger.policy import load_manifest_file, resolve_manifest

WICKET_CATALOG_DIR = Path(__file__).parent.parent / "asg_ledger" / "guards" / "wickets" / "catalog_defs"
FOLD_CATALOG_DIR = Path(__file__).parent.parent / "asg_ledger" / "folds" / "catalog_defs"
DEFAULT_MANIFEST_PATH = Path(__file__).parent.parent / "asg_ledger" / "policy" / "catalog_defs" / "default.yaml"

EXPECTED_DEFAULT_DIGEST = "0e99f3ee3a6ebf3ee93aa464f27e8fcd1a401ccc45460eb267efde327f5c218c"


def test_manifest_show_prints_digest_and_ok_for_every_ref(capsys):
    rc = main(["manifest", "show"])
    assert rc == 0
    out = capsys.readouterr().out
    assert f"manifest default/1.0.0  {EXPECTED_DEFAULT_DIGEST}" in out
    assert "fold    spend.weekly/1.0.0" in out
    assert "wicket  caps/1.0.0" in out
    assert out.count("OK") == 4  # 1 fold + 3 wickets


def test_manifest_show_reports_drift_as_a_clean_failure(tmp_path, capsys):
    """The mutant: a real config edit under the catalog `manifest show`
    resolves against MUST be rejected, not silently accepted."""
    mutant_dir = tmp_path / "wickets"
    shutil.copytree(WICKET_CATALOG_DIR, mutant_dir)
    caps_path = mutant_dir / "caps.yaml"
    caps_path.write_text(caps_path.read_text().replace("10000000", "99999999"))

    rc = main(["manifest", "show", "--wicket-dir", str(mutant_dir)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "FAIL wicket_digest_drift" in err


def test_manifest_activate_appends_a_config_change_capsule(tmp_path, capsys):
    ledger_dir = tmp_path / "store"
    rc = main(["manifest", "activate", "--ledger", str(ledger_dir), "--operator", "acme", "--developer", "ops"])
    assert rc == 0
    out = capsys.readouterr().out
    assert f"activated manifest default/1.0.0  {EXPECTED_DEFAULT_DIGEST}" in out
    assert "capsule " in out
    assert "chained to previous activation" not in out

    store = LedgerStore(ledger_dir)
    records = list(store.scan())
    store.close()
    assert len(records) == 1
    assert records[0].capsule["asg_payload"]["event"] == "policy_manifest_activated"
    assert records[0].capsule["asg_payload"]["detail"]["manifest_digest"] == EXPECTED_DEFAULT_DIGEST
    assert records[0].capsule["chain"]["relation"] == "epoch_opens"


def test_manifest_activate_twice_chains_to_the_first(tmp_path, capsys):
    ledger_dir = tmp_path / "store"
    main(["manifest", "activate", "--ledger", str(ledger_dir), "--operator", "acme", "--developer", "ops"])
    capsys.readouterr()
    rc = main(["manifest", "activate", "--ledger", str(ledger_dir), "--operator", "acme", "--developer", "ops"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "chained to previous activation" in out

    store = LedgerStore(ledger_dir)
    records = list(store.scan())
    store.close()
    assert len(records) == 2
    assert records[1].capsule["chain"]["parent_capsule_id"] == records[0].capsule_id


def test_manifest_activate_requires_ledger(capsys):
    rc = main(["manifest", "activate", "--operator", "acme", "--developer", "ops"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "--ledger is required" in err


def test_manifest_verify_ok_against_a_real_decision_capsule(tmp_path, capsys):
    ledger_dir = tmp_path / "store"
    manifest = load_manifest_file(DEFAULT_MANIFEST_PATH)
    resolved = resolve_manifest(manifest, fold_catalog_dir=FOLD_CATALOG_DIR, wicket_catalog_dir=WICKET_CATALOG_DIR)
    signer = LocalSigner(key_id="k", secret=b"s")

    store = LedgerStore(ledger_dir)
    engine = GuardEngine(
        ledger=store, caps_fold=resolved.caps_fold(), signer_provider=lambda: signer,
        manifest_digest=resolved.manifest_digest,
    )
    action = Action(verb="info_lookup", operator="acme", developer="dev1", action_class="info.query")
    decision = engine.check(action)
    store.close()

    rc = main(["manifest", "verify", "--ledger", str(ledger_dir), "--capsule", decision.capsule["capsule_id"]])
    assert rc == 0
    out = capsys.readouterr().out
    assert "OK: capsule" in out
    assert "was decided under manifest default/1.0.0" in out


def test_manifest_verify_fails_when_capsule_cites_no_manifest_digest(tmp_path, capsys):
    ledger_dir = tmp_path / "store"
    fold = load_manifest_file(DEFAULT_MANIFEST_PATH)
    resolved = resolve_manifest(fold, fold_catalog_dir=FOLD_CATALOG_DIR, wicket_catalog_dir=WICKET_CATALOG_DIR)
    signer = LocalSigner(key_id="k", secret=b"s")

    store = LedgerStore(ledger_dir)
    engine = GuardEngine(ledger=store, caps_fold=resolved.caps_fold(), signer_provider=lambda: signer)  # no manifest_digest
    action = Action(verb="info_lookup", operator="acme", developer="dev1", action_class="info.query")
    decision = engine.check(action)
    store.close()

    rc = main(["manifest", "verify", "--ledger", str(ledger_dir), "--capsule", decision.capsule["capsule_id"]])
    assert rc == 1
    err = capsys.readouterr().err
    assert "cites no manifest_digest" in err


def test_manifest_verify_fails_when_capsule_not_found(tmp_path, capsys):
    ledger_dir = tmp_path / "store"
    LedgerStore(ledger_dir).close()
    rc = main(["manifest", "verify", "--ledger", str(ledger_dir), "--capsule", "deadbeef"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "no such capsule" in err


def test_manifest_verify_fails_on_mismatched_digest(tmp_path, capsys):
    """The mutant: a capsule citing a digest that does NOT match the
    resolved manifest must fail, not pass by coincidence."""
    ledger_dir = tmp_path / "store"
    fold = load_manifest_file(DEFAULT_MANIFEST_PATH)
    resolved = resolve_manifest(fold, fold_catalog_dir=FOLD_CATALOG_DIR, wicket_catalog_dir=WICKET_CATALOG_DIR)
    signer = LocalSigner(key_id="k", secret=b"s")

    store = LedgerStore(ledger_dir)
    engine = GuardEngine(
        ledger=store, caps_fold=resolved.caps_fold(), signer_provider=lambda: signer, manifest_digest="f" * 64
    )
    action = Action(verb="info_lookup", operator="acme", developer="dev1", action_class="info.query")
    decision = engine.check(action)
    store.close()

    rc = main(["manifest", "verify", "--ledger", str(ledger_dir), "--capsule", decision.capsule["capsule_id"]])
    assert rc == 1
    err = capsys.readouterr().err
    assert "FAIL: capsule cites manifest_digest" in err
