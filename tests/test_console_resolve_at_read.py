# SPDX-License-Identifier: Apache-2.0
"""Console-side wiring for ldg-registry-driven-viewer items 2/3/5a:
action_class convention labels, assurance grades, and resolve-at-read in
`capsule console`'s JSON API, over a real, local, directory-backed
``LedgerStore`` (never the imported-JSONL-fixture case, which
``test_cli_console.py`` already covers for the rest of the API)."""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest
from agent_action_capsule import json_digest

from capsule_ledger.console.server import build_server
from capsule_ledger.ledger import LedgerStore
from capsule_ledger.payload_store import PayloadStore

EVIDENCE = {"threshold_minor": 1000000, "observed_minor": 1200000}
REASON = {"policy": "weekly-cap", "note": "over the line"}
EVIDENCE_DIGEST = json_digest(EVIDENCE)
REASON_DIGEST = json_digest(REASON)
CAPSULE_ID = "b" * 64


def _capsule(*, action_class="money.transfer", assurance_mode="self_attested"):
    cap = {
        "capsule_id": CAPSULE_ID,
        "operator": "acme",
        "developer": "agent-1",
        "action_id": "approve_purchase/1",
        "action_type": "decide",
        "timestamp": "2026-08-11T00:00:00Z",
        "assurance": {"attestation_mode": assurance_mode, "effect_mode": "not_applicable", "ledger_mode": "standalone"},
        "disposition": {"decision": "reject", "verdict_class": "blocked", "reason_digest": REASON_DIGEST},
        "constraints": [{"id": "caps", "result": "fail", "evidence_digest": EVIDENCE_DIGEST}],
    }
    if action_class:
        cap["asg_payload"] = {"action_class": action_class}
    return cap


def _start_server(ledger_path):
    box: dict = {}
    ready = threading.Event()

    def _serve():
        server = build_server(str(ledger_path), host="127.0.0.1", port=0)
        box["server"] = server
        ready.set()
        try:
            server.serve_forever()
        finally:
            server.server_close()

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()
    assert ready.wait(timeout=5), "console server did not start"
    return box["server"], thread


def _stop_server(server, thread) -> None:
    server.shutdown()
    thread.join(timeout=5)


def _get_json(url: str):
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


@pytest.fixture
def local_ledger(tmp_path):
    root = tmp_path / "ledger"
    store = LedgerStore(root)
    store.append(_capsule(), consequential=False)
    store.close()
    return root


def _with_server(ledger_root, fn):
    server, thread = _start_server(ledger_root)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        return fn(base)
    finally:
        _stop_server(server, thread)


def test_records_endpoint_includes_action_class_and_assurance_grade(local_ledger):
    def check(base):
        status, data = _get_json(base + "/api/records")
        assert status == 200
        record = data["records"][0]
        assert record["action_class"] == {"value": "money.transfer", "label": "Money transfer", "registered": True}
        assert record["assurance_grade"] == {"grade": "self-attested · ledger: standalone", "badged": False}

    _with_server(local_ledger, check)


def test_records_endpoint_marks_unregistered_action_class(tmp_path):
    root = tmp_path / "ledger"
    store = LedgerStore(root)
    store.append(_capsule(action_class="hold.reserve"), consequential=False)
    store.close()

    def check(base):
        status, data = _get_json(base + "/api/records")
        assert status == 200
        assert data["records"][0]["action_class"] == {"value": "hold.reserve", "label": "hold.reserve", "registered": False}

    _with_server(root, check)


def test_records_endpoint_omits_action_class_when_capsule_carries_none(tmp_path):
    root = tmp_path / "ledger"
    store = LedgerStore(root)
    store.append(_capsule(action_class=None), consequential=False)
    store.close()

    def check(base):
        status, data = _get_json(base + "/api/records")
        assert status == 200
        assert data["records"][0]["action_class"] is None

    _with_server(root, check)


def test_records_endpoint_badges_anchored_assurance(tmp_path):
    root = tmp_path / "ledger"
    store = LedgerStore(root)
    store.append(_capsule(assurance_mode="anchored"), consequential=False)
    store.close()

    def check(base):
        status, data = _get_json(base + "/api/records")
        assert status == 200
        assert data["records"][0]["assurance_grade"]["badged"] is True

    _with_server(root, check)


def test_detail_endpoint_does_not_resolve_without_a_payload_store(local_ledger):
    def check(base):
        status, detail = _get_json(base + "/api/records/" + CAPSULE_ID)
        assert status == 200
        assert detail["resolved_reason"] is None
        assert detail["checks"][0]["evidence_digest"] == EVIDENCE_DIGEST
        assert detail["checks"][0]["resolved_evidence"] is None

    _with_server(local_ledger, check)


def test_detail_endpoint_resolves_matching_payloads(local_ledger):
    store = PayloadStore(local_ledger)
    store.put(EVIDENCE)
    store.put(REASON)

    def check(base):
        status, detail = _get_json(base + "/api/records/" + CAPSULE_ID)
        assert status == 200
        assert detail["resolved_reason"]["match"] is True
        assert detail["resolved_reason"]["content"] == REASON
        assert detail["checks"][0]["resolved_evidence"]["match"] is True
        assert detail["checks"][0]["resolved_evidence"]["content"] == EVIDENCE

    _with_server(local_ledger, check)


def test_detail_endpoint_reports_a_tampered_local_copy(local_ledger):
    store = PayloadStore(local_ledger)
    store.put(EVIDENCE)
    tampered = (local_ledger / "payloads" / f"{EVIDENCE_DIGEST}.json")
    tampered.write_text(json.dumps({"threshold_minor": 1}), encoding="utf-8")

    def check(base):
        status, detail = _get_json(base + "/api/records/" + CAPSULE_ID)
        assert status == 200
        resolved = detail["checks"][0]["resolved_evidence"]
        assert resolved is not None
        assert resolved["match"] is False
        assert resolved["recomputed_digest"] != resolved["digest"]

    _with_server(local_ledger, check)
