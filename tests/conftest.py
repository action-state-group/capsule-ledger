# SPDX-License-Identifier: Apache-2.0
import pytest

from capsule_ledger.ledger import LedgerStore
from capsule_ledger.ledger.signing import LocalSigner


@pytest.fixture
def store(tmp_path):
    s = LedgerStore(tmp_path)
    yield s
    s.close()


@pytest.fixture
def signer():
    return LocalSigner(key_id="test-key-1", secret=b"test-secret")
