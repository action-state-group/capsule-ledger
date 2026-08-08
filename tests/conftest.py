# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

import pytest

from capsule_ledger.folds.loader import load_definition_file
from capsule_ledger.guards import LocalSigner
from capsule_ledger.ledger import LedgerStore

CATALOG_DIR = Path(__file__).parent.parent / "capsule_ledger" / "folds" / "catalog_defs"
WICKET_CATALOG_DIR = Path(__file__).parent.parent / "capsule_ledger" / "guards" / "wickets" / "catalog_defs"
DEFAULT_MANIFEST_PATH = Path(__file__).parent.parent / "capsule_ledger" / "policy" / "catalog_defs" / "default.yaml"
HOLDS_MANIFEST_PATH = Path(__file__).parent.parent / "capsule_ledger" / "policy" / "catalog_defs" / "holds.yaml"


@pytest.fixture
def store(tmp_path):
    s = LedgerStore(tmp_path)
    yield s
    s.close()


@pytest.fixture
def caps_fold():
    return load_definition_file(CATALOG_DIR / "spend.weekly.yaml")


@pytest.fixture
def signer():
    return LocalSigner(key_id="test-key-1", secret=b"test-secret")


@pytest.fixture
def resolved_manifest():
    from capsule_ledger.policy import load_manifest_file, resolve_manifest

    manifest = load_manifest_file(DEFAULT_MANIFEST_PATH)
    return resolve_manifest(manifest, fold_catalog_dir=CATALOG_DIR, wicket_catalog_dir=WICKET_CATALOG_DIR)


@pytest.fixture
def hold_fold():
    return load_definition_file(CATALOG_DIR / "hold.active_exposure.yaml")


@pytest.fixture
def resolved_holds_manifest():
    from capsule_ledger.policy import load_manifest_file, resolve_manifest

    manifest = load_manifest_file(HOLDS_MANIFEST_PATH)
    return resolve_manifest(manifest, fold_catalog_dir=CATALOG_DIR, wicket_catalog_dir=WICKET_CATALOG_DIR)


@pytest.fixture
def hold_engine(store, hold_fold, signer, resolved_holds_manifest):
    from capsule_ledger.holds import HoldEngine, resolve_hold_policy

    policy = resolve_hold_policy(resolved_holds_manifest)
    return HoldEngine(
        ledger=store,
        hold_fold=hold_fold,
        fold_digest=policy.fold_digest,
        signer_provider=lambda: signer,
        cap_minor=policy.caps_minor,
        tolerance_minor=policy.tolerance_minor,
        manifest_digest=resolved_holds_manifest.manifest_digest,
    )
