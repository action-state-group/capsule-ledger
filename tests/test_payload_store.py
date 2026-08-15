# SPDX-License-Identifier: Apache-2.0
"""``payload_store.PayloadStore``: the resolve-at-read (item 5a) store
itself, independent of any CLI/console wiring."""
from __future__ import annotations

import json

from agent_action_capsule import json_digest

from capsule_ledger.payload_store import PayloadStore


def test_store_does_not_exist_until_something_is_put(tmp_path):
    store = PayloadStore(tmp_path)
    assert store.exists is False
    store.put({"a": 1})
    assert store.exists is True


def test_put_returns_the_real_json_digest(tmp_path):
    store = PayloadStore(tmp_path)
    payload = {"threshold_minor": 1000000, "observed_minor": 1200000}
    digest = store.put(payload)
    assert digest == json_digest(payload)


def test_resolve_returns_none_for_an_unknown_digest(tmp_path):
    store = PayloadStore(tmp_path)
    store.put({"a": 1})
    assert store.resolve("f" * 64) is None


def test_resolve_returns_none_when_the_store_does_not_exist_at_all(tmp_path):
    store = PayloadStore(tmp_path)  # never put() -- directory never created
    assert store.resolve("f" * 64) is None


def test_resolve_returns_none_for_a_falsy_digest(tmp_path):
    store = PayloadStore(tmp_path)
    store.put({"a": 1})
    assert store.resolve(None) is None
    assert store.resolve("") is None


def test_resolve_matches_and_recomputes_live(tmp_path):
    store = PayloadStore(tmp_path)
    payload = {"policy": "weekly-cap", "note": "over by 200000 minor units"}
    digest = store.put(payload)

    resolved = store.resolve(digest)
    assert resolved is not None
    assert resolved.digest == digest
    assert resolved.recomputed_digest == digest
    assert resolved.match is True
    assert resolved.content == payload


def test_resolve_detects_a_tampered_local_copy_loudly(tmp_path):
    """A corrupted/edited local file under the digest-named path must fail
    loudly (mismatch), never silently pass as if it were the real preimage."""
    store = PayloadStore(tmp_path)
    payload = {"threshold_minor": 1000000}
    digest = store.put(payload)

    # Tamper with the stored file directly, without touching its filename.
    (tmp_path / "payloads" / f"{digest}.json").write_text(
        json.dumps({"threshold_minor": 999}), encoding="utf-8"
    )

    resolved = store.resolve(digest)
    assert resolved is not None
    assert resolved.match is False
    assert resolved.recomputed_digest != digest
    assert resolved.digest == digest  # still reports what the record actually claims


def test_two_different_ledger_roots_have_independent_stores(tmp_path):
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    store_a = PayloadStore(root_a)
    store_b = PayloadStore(root_b)
    digest = store_a.put({"only": "in-a"})
    assert store_b.resolve(digest) is None
