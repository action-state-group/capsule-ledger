from pathlib import Path

import pytest

from asg_ledger.folds.loader import load_definition_file
from asg_ledger.guards import LocalSigner
from asg_ledger.ledger import LedgerStore

CATALOG_DIR = Path(__file__).parent.parent / "asg_ledger" / "folds" / "catalog_defs"


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
