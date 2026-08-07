# SPDX-License-Identifier: Apache-2.0
"""Tests for the two-agent demo/fixture generator.

Three concerns, matching the task's own acceptance bar: (1) the four
scenarios genuinely hit real guard verdicts, not just "the script didn't
crash"; (2) the same seed reproduces byte-identical output, and a different
seed does not; (3) the committed fixture is a real, independently loadable
and verifiable ledger, not just script output.
"""
from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path
from unittest import mock

import pytest

from capsule_ledger.examples.remote_ledger import RemoteLedgerAPI
from capsule_ledger.examples.two_agents import DEFAULT_SEED, run_simulation
from capsule_ledger.guards import ALLOW, DENY, ESCALATE
from capsule_ledger.ledger import LedgerStore, ScanQuery

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "two_agents_sim_ledger.jsonl"


# -- scenario 1-4: real guard verdicts, not just "it ran" -------------------


def test_scenarios_hit_real_guard_verdicts(tmp_path):
    result = run_simulation(local_store_dir=str(tmp_path / "store"), seed=DEFAULT_SEED)

    assert result.outcomes["overlap_spend_alpha"] == ALLOW
    assert result.outcomes["overlap_spend_beta_escalated"] == ESCALATE
    assert result.outcomes["dedupe_original"] == ALLOW
    assert result.outcomes["dedupe_collision"] == DENY
    assert result.outcomes["refusal"] == DENY
    assert result.outcomes["intent_fulfill"] == ALLOW
    assert len(result.records) == 7

    by_id = {r.capsule_id: r for r in result.records}

    # Scenario 1: overlapping spend against the shared treasury cap escalates
    # (D2: money.transfer has an approver_role, so a pure cap-exceeded hold
    # routes to a human instead of hard-denying).
    escalated = by_id[result.capsule_ids["overlap_spend_beta_escalated"]]
    assert escalated.capsule["disposition"]["decision"] == "hitl_dispatched"
    assert escalated.capsule["disposition"]["verdict_class"] == "hitl_dispatched"
    caps_constraint = next(c for c in escalated.capsule["constraints"] if c["id"] == "caps")
    assert caps_constraint["result"] == "fail"

    # Scenario 2: the second identical submission is a real dedupe collision,
    # hard-denied and chained back to the original via chain.parent_capsule_id.
    collision = by_id[result.capsule_ids["dedupe_collision"]]
    dedupe_constraint = next(c for c in collision.capsule["constraints"] if c["id"] == "dedupe")
    assert dedupe_constraint["result"] == "fail"
    assert collision.capsule["disposition"]["decision"] == "reject"
    assert collision.capsule["chain"] == {
        "parent_capsule_id": result.capsule_ids["dedupe_original"],
        "relation": "confirms",
    }

    # Scenario 3: the refusal is a real verify_before_dispatch integrity
    # failure (the cited mandate was never recorded), hard-denied.
    refusal = by_id[result.capsule_ids["refusal"]]
    vbd_constraint = next(c for c in refusal.capsule["constraints"] if c["id"] == "verify_before_dispatch")
    assert vbd_constraint["result"] == "fail"
    assert refusal.capsule["disposition"]["decision"] == "reject"

    # Scenario 4: the fulfilling action is chained to the intent-declare
    # capsule capsule-emit produced, and is genuinely allowed.
    fulfill = by_id[result.capsule_ids["intent_fulfill"]]
    assert fulfill.capsule["chain"] == {
        "parent_capsule_id": result.capsule_ids["intent_declare"],
        "relation": "confirms",
    }
    intent = by_id[result.capsule_ids["intent_declare"]]
    assert intent.capsule["action_id"].startswith("intent.declare/")
    assert intent.capsule["developer"] == "checkout-agent-alpha@v1"

    # Distinct signing identities: the two agents' guard decisions are
    # signed by two different keys.
    alpha_capsule = by_id[result.capsule_ids["overlap_spend_alpha"]]
    beta_capsule = by_id[result.capsule_ids["overlap_spend_beta_escalated"]]
    assert alpha_capsule.capsule["asg_signature"]["key_id"] != beta_capsule.capsule["asg_signature"]["key_id"]


# -- reproducibility ---------------------------------------------------------


def test_reproducible_byte_identical(tmp_path):
    out_1 = tmp_path / "run1.jsonl"
    out_2 = tmp_path / "run2.jsonl"
    run_simulation(local_store_dir=str(tmp_path / "store1"), seed=DEFAULT_SEED, fixture_out=out_1)
    run_simulation(local_store_dir=str(tmp_path / "store2"), seed=DEFAULT_SEED, fixture_out=out_2)

    assert out_1.read_bytes() == out_2.read_bytes()
    assert out_1.stat().st_size > 0


def test_different_seed_changes_output(tmp_path):
    out_a = tmp_path / "seed_a.jsonl"
    out_b = tmp_path / "seed_b.jsonl"
    run_simulation(local_store_dir=str(tmp_path / "store_a"), seed=1, fixture_out=out_a)
    run_simulation(local_store_dir=str(tmp_path / "store_b"), seed=2, fixture_out=out_b)

    assert out_a.read_bytes() != out_b.read_bytes()


# -- the committed fixture is a real, reusable ledger ------------------------


def test_committed_fixture_is_loadable_and_verifiable(tmp_path):
    assert FIXTURE_PATH.exists(), f"missing committed fixture: {FIXTURE_PATH}"

    store = LedgerStore(tmp_path / "imported-store")
    try:
        n = store.import_jsonl(FIXTURE_PATH)
        assert n == 7

        escalated = list(store.scan(ScanQuery(verdict="hitl_dispatched")))
        assert len(escalated) == 1

        blocked = list(store.scan(ScanQuery(verdict="blocked")))
        assert len(blocked) == 2  # dedupe collision + refusal

        # Every capsule in the fixture -- including the one capsule-emit
        # (not the guard) produced -- independently re-verifies.
        for record in store.scan():
            result = store.verify(record.capsule_id)
            assert result is not None and result.ok, (record.capsule_id, result.findings if result else None)
    finally:
        store.close()


def test_committed_fixture_matches_freshly_regenerated_output(tmp_path):
    """The committed fixture is exactly what a fresh run with the default
    seed produces -- it is not stale, hand-edited, or out of sync with the
    generator that produced it."""
    out = tmp_path / "regenerated.jsonl"
    run_simulation(local_store_dir=str(tmp_path / "store"), seed=DEFAULT_SEED, fixture_out=out)
    assert out.read_bytes() == FIXTURE_PATH.read_bytes()


# -- RemoteLedgerAPI: HTTP request shape, no real network --------------------


class _FakeResponse:
    def __init__(self, payload) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def test_remote_ledger_api_append_posts_capsule_and_parses_record():
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["body"] = json.loads(req.data)
        captured["api_key"] = req.get_header("X-api-key")
        return _FakeResponse(
            {"seq": 1, "capsule_id": "abc123", "capsule": {"x": 1}, "segment": "seg-0", "consequential": True}
        )

    client = RemoteLedgerAPI("https://tenant.example.com/", "demo-api-key")
    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
        record = client.append({"x": 1}, consequential=True)

    assert captured["url"] == "https://tenant.example.com/v1/capsules"
    assert captured["method"] == "POST"
    assert captured["body"] == {"capsule": {"x": 1}, "consequential": True}
    assert captured["api_key"] == "demo-api-key"
    assert record.capsule_id == "abc123"
    assert record.seq == 1


def test_remote_ledger_api_scan_builds_query_and_yields_records():
    def fake_urlopen(req, timeout=None):
        assert req.get_method() == "GET"
        assert req.full_url.startswith("https://tenant.example.com/v1/capsules?")
        assert "agent=agent-a" in req.full_url
        return _FakeResponse([{"seq": 1, "capsule_id": "a", "capsule": {}, "segment": "s", "consequential": True}])

    client = RemoteLedgerAPI("https://tenant.example.com", "key")
    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
        records = list(client.scan(ScanQuery(agent="agent-a")))

    assert len(records) == 1
    assert records[0].capsule_id == "a"


def test_remote_ledger_api_fetch_missing_returns_none():
    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 404, "not found", None, io.BytesIO(b""))

    client = RemoteLedgerAPI("https://tenant.example.com", "key")
    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
        assert client.fetch("does-not-exist") is None


def test_remote_ledger_api_verify_parses_findings():
    def fake_urlopen(req, timeout=None):
        assert req.full_url == "https://tenant.example.com/v1/capsules/abc/verify"
        return _FakeResponse(
            {
                "ok": False,
                "findings": [{"code": "digest_mismatch", "detail": "bad", "severity": "error", "check": 1}],
                "assurance": {},
                "capsule_id": "abc",
            }
        )

    client = RemoteLedgerAPI("https://tenant.example.com", "key")
    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = client.verify("abc")

    assert result is not None
    assert result.ok is False
    assert result.findings[0].code == "digest_mismatch"


def test_remote_ledger_api_find_gaps_not_implemented():
    client = RemoteLedgerAPI("https://tenant.example.com", "key")
    with pytest.raises(NotImplementedError):
        client.find_gaps()


# -- backend config seam ------------------------------------------------------


def test_run_simulation_remote_backend_requires_base_url_and_api_key():
    with pytest.raises(RuntimeError, match="requires a base URL and API key"):
        run_simulation(backend="remote")


def test_run_simulation_unknown_backend_raises():
    with pytest.raises(NotImplementedError):
        run_simulation(backend="carrier-pigeon")
