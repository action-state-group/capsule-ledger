# SPDX-License-Identifier: Apache-2.0
"""`capsule diff` renders a policy-manifest activation as a distinct
boundary event, never silently absorbed into the ordinary added-record
count (task acceptance point 5)."""
from __future__ import annotations

import json
from pathlib import Path

from asg_ledger.cli.main import main
from asg_ledger.guards import Action, GuardEngine, LocalSigner
from asg_ledger.ledger import LedgerStore
from asg_ledger.policy import build_manifest_activation_capsule, load_manifest_file, resolve_manifest

FOLD_CATALOG_DIR = Path(__file__).parent.parent / "asg_ledger" / "folds" / "catalog_defs"
WICKET_CATALOG_DIR = Path(__file__).parent.parent / "asg_ledger" / "guards" / "wickets" / "catalog_defs"
DEFAULT_MANIFEST_PATH = Path(__file__).parent.parent / "asg_ledger" / "policy" / "catalog_defs" / "default.yaml"

EXPECTED_DEFAULT_DIGEST = "0e99f3ee3a6ebf3ee93aa464f27e8fcd1a401ccc45460eb267efde327f5c218c"


def _seed(ledger_dir: Path) -> None:
    manifest = load_manifest_file(DEFAULT_MANIFEST_PATH)
    resolved = resolve_manifest(manifest, fold_catalog_dir=FOLD_CATALOG_DIR, wicket_catalog_dir=WICKET_CATALOG_DIR)
    signer = LocalSigner(key_id="k", secret=b"s")

    store = LedgerStore(ledger_dir)
    activation = build_manifest_activation_capsule(resolved=resolved, operator="acme", developer="ops", signer=signer)
    store.append(activation, consequential=False)

    engine = GuardEngine(ledger=store, caps_fold=resolved.caps_fold(), signer_provider=lambda: signer)
    action = Action(verb="info_lookup", operator="acme", developer="dev1", action_class="info.query")
    engine.check(action)
    store.close()


def test_manifest_activation_renders_as_a_boundary_not_a_plain_added_record(tmp_path, capsys):
    ledger_dir = tmp_path / "store"
    _seed(ledger_dir)

    rc = main(["diff", "0", "HEAD", "--ledger", str(ledger_dir)])
    assert rc == 0
    out = capsys.readouterr().out

    assert "1 manifest boundary event(s):" in out
    assert "manifest default/1.0.0" in out
    assert EXPECTED_DEFAULT_DIGEST[:16] in out
    # The boundary event must not also be counted among ordinary new records.
    assert "1 new record(s):" in out  # only the info_lookup decision


def test_manifest_boundary_appears_before_ordinary_added_records(tmp_path, capsys):
    ledger_dir = tmp_path / "store"
    _seed(ledger_dir)
    rc = main(["diff", "0", "HEAD", "--ledger", str(ledger_dir)])
    assert rc == 0
    out = capsys.readouterr().out
    assert out.index("manifest boundary event(s):") < out.index("new record(s):")


def test_manifest_boundary_in_json_output(tmp_path, capsys):
    ledger_dir = tmp_path / "store"
    _seed(ledger_dir)
    rc = main(["diff", "0", "HEAD", "--ledger", str(ledger_dir), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)

    assert len(payload["manifest_boundaries"]) == 1
    boundary = payload["manifest_boundaries"][0]
    assert boundary["manifest_id"] == "default/1.0.0"
    assert boundary["manifest_digest"] == EXPECTED_DEFAULT_DIGEST
    # The boundary's capsule_id must not also appear in "added".
    assert boundary["capsule_id"] not in payload["added"]
    assert len(payload["added"]) == 1


def test_no_boundary_when_no_manifest_was_ever_activated(tmp_path, capsys):
    ledger_dir = tmp_path / "store"
    manifest = load_manifest_file(DEFAULT_MANIFEST_PATH)
    resolved = resolve_manifest(manifest, fold_catalog_dir=FOLD_CATALOG_DIR, wicket_catalog_dir=WICKET_CATALOG_DIR)
    signer = LocalSigner(key_id="k", secret=b"s")
    store = LedgerStore(ledger_dir)
    engine = GuardEngine(ledger=store, caps_fold=resolved.caps_fold(), signer_provider=lambda: signer)
    action = Action(verb="info_lookup", operator="acme", developer="dev1", action_class="info.query")
    engine.check(action)
    store.close()

    rc = main(["diff", "0", "HEAD", "--ledger", str(ledger_dir), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["manifest_boundaries"] == []
    assert len(payload["added"]) == 1
