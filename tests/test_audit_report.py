# SPDX-License-Identifier: Apache-2.0
"""``capsule report`` (design §3.6) end to end: collect the three blocks
from a ledger, seal the report as a level-3 record, bundle it, and prove an
auditor can verify a sampled row offline -- no network, no permission from
us (the P4 acceptance line)."""
from __future__ import annotations

import hashlib
import json
import socket
from pathlib import Path

import pytest
from agent_action_capsule import verify as verify_capsule

from capsule_ledger.audit_report import build_period_report, render_text, seal_period_report_capsule
from capsule_ledger.audit_report.collect import statement_digest
from capsule_ledger.cli.main import main as cli_main
from capsule_ledger.compiler.acceptance import (
    build_declaration_acceptance_capsule,
    build_refusal_acknowledgment_capsule,
)
from capsule_ledger.compiler.compilation_record import build_compilation_record_capsule
from capsule_ledger.compiler.offer_response import build_offer_capsule, build_response_capsule
from capsule_ledger.compiler.refusal import build_refusal_capsule
from capsule_ledger.compiler.scope_census import build_scope_census_capsule
from capsule_ledger.compiler.vocabulary import RESERVED_VERDICT_WORDS, VerdictPair, display_string
from capsule_ledger.packs.loader import load_pack_dir

OPERATOR = "test-operator"
DEVELOPER = "test-developer@v1"

PACK_DIR = Path(__file__).parent / "fixtures" / "packs" / "retail_synthetic_shaped"

OUTCOME_EXCHANGE = "outcome.exchange_recommended_and_acted_on"
OUTCOME_REFUND = "outcome.refund_confirmed"
OUTCOME_RESPONDED = "outcome.customer_responded_to_exchange_offer"
OUTCOME_CAUSED = "outcome.agent_caused_customer_satisfaction"


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.fixture
def pack():
    return load_pack_dir(PACK_DIR)


def _seed_ledger(store, signer, *, ts="2026-08-01T00:00:00Z"):
    """A small, hand-built ledger exercising every block: T2 census, T1
    acceptance, compilation record C, three offer/response pairs for the
    exchange outcome (accepted/declined/deferred -- exercising the
    denominator and the deferral register), and a refusal + T4
    acknowledgment for the refused outcome."""
    census = build_scope_census_capsule(
        document_digest=_digest("doc"), n=4, m=6, review_by="2027-01-01",
        operator=OPERATOR, developer=DEVELOPER, signer=signer, timestamp=ts,
    )
    store.append(census)

    compilation = build_compilation_record_capsule(
        d_digest=_digest("D"), p_digest=_digest("P"), f_digest=_digest("F"),
        compiler_id="capsule_ledger.compiler", compiler_version="0.1.0",
        operator=OPERATOR, developer=DEVELOPER, signer=signer, timestamp=ts,
    )
    store.append(compilation)

    acceptance = build_declaration_acceptance_capsule(
        d_digest=_digest("D"), c_digest=compilation["capsule_id"], accepted_by="vendor",
        operator=OPERATOR, developer=DEVELOPER, signer=signer, timestamp=ts,
    )
    store.append(acceptance)

    ids = {"census": census["capsule_id"], "compilation": compilation["capsule_id"], "acceptance": acceptance["capsule_id"]}

    # Three exchange offers: accepted, declined, deferred -- N=1 accepted of M=3.
    for i, response_class in enumerate(["accepted", "declined", "deferred"], start=1):
        offer = build_offer_capsule(
            offer_id=f"{OUTCOME_EXCHANGE}/{i}", offer_digest=_digest(f"offer-{i}"),
            operator=OPERATOR, developer=DEVELOPER, signer=signer, timestamp=ts,
        )
        store.append(offer)
        response = build_response_capsule(
            offer_id=f"{OUTCOME_EXCHANGE}/{i}", offer_capsule_id=offer["capsule_id"],
            response_class=response_class,
            response_digest=_digest(f"response-{i}") if response_class != "no_response" else None,
            operator=OPERATOR, developer=DEVELOPER, signer=signer, timestamp=ts,
        )
        store.append(response)
        ids[f"offer_{i}"] = offer["capsule_id"]
        ids[f"response_{i}"] = response["capsule_id"]

    return ids


def _seed_refusal(store, signer, pack, *, ts="2026-08-01T00:00:00Z", acknowledge=True):
    outcome = pack.outcome_for_id(OUTCOME_CAUSED)
    refusal = build_refusal_capsule(
        verdict=VerdictPair(forward=outcome.forward_verdict, backward=outcome.backward_verdict),
        statement_digest=statement_digest(outcome.statement),
        reason_code=outcome.refusal_reason_code,
        operator=OPERATOR, developer=DEVELOPER, signer=signer, timestamp=ts,
    )
    store.append(refusal)
    ack_id = None
    if acknowledge:
        ack = build_refusal_acknowledgment_capsule(
            refusal_capsule_id=refusal["capsule_id"], acknowledged_by="grc-reviewer",
            operator=OPERATOR, developer=DEVELOPER, signer=signer, timestamp=ts,
        )
        store.append(ack)
        ack_id = ack["capsule_id"]
    return refusal["capsule_id"], ack_id


def test_promised_block_reads_t1_t2_c(store, signer, pack):
    _seed_ledger(store, signer)
    report = build_period_report(
        store, pack, audience="auditor", since=None, until=None, generated_at="2026-08-10T00:00:00Z"
    )
    p = report.promised
    assert (p.census_n, p.census_m, p.census_review_by) == (4, 6, "2027-01-01")
    assert p.accepted_by == "vendor"
    assert p.d_digest == _digest("D")
    assert p.c_digest is not None


def test_promised_block_is_honest_when_nothing_recorded(store, signer, pack):
    report = build_period_report(
        store, pack, audience="auditor", since=None, until=None, generated_at="2026-08-10T00:00:00Z"
    )
    p = report.promised
    assert p.census_capsule_id is None
    assert p.acceptance_capsule_id is None
    assert p.c_digest is None


def test_coverage_row_denominator_is_n_of_m_not_a_percentage(store, signer, pack):
    _seed_ledger(store, signer)
    report = build_period_report(
        store, pack, audience="auditor", since=None, until=None, generated_at="2026-08-10T00:00:00Z"
    )
    row = next(r for r in report.happened.coverage if r.outcome_id == OUTCOME_EXCHANGE)
    assert (row.n, row.m) == (1, 3)
    assert row.forward_display == display_string("forward_verdict", "DETERMINISTIC")
    assert row.backward_display == display_string("backward_verdict", "DETERMINISTIC")


def test_coverage_row_is_honest_zero_of_zero_when_no_evidence_shaped_capsules_exist(store, signer, pack):
    _seed_ledger(store, signer)
    report = build_period_report(
        store, pack, audience="auditor", since=None, until=None, generated_at="2026-08-10T00:00:00Z"
    )
    row = next(r for r in report.happened.coverage if r.outcome_id == OUTCOME_REFUND)
    assert (row.n, row.m) == (0, 0)


def test_not_claimable_register_carries_with_instrumentation_outcome(store, signer, pack):
    _seed_ledger(store, signer)
    report = build_period_report(
        store, pack, audience="auditor", since=None, until=None, generated_at="2026-08-10T00:00:00Z"
    )
    row = next(r for r in report.happened.not_claimable if r.outcome_id == OUTCOME_RESPONDED)
    assert row.reason_category == "with_instrumentation"
    assert row.reason_display == display_string("backward_verdict", "WITH-INSTRUMENTATION")


def test_not_claimable_register_carries_refused_outcome_with_signed_acknowledgment(store, signer, pack):
    _seed_ledger(store, signer)
    refusal_id, ack_id = _seed_refusal(store, signer, pack)
    report = build_period_report(
        store, pack, audience="auditor", since=None, until=None, generated_at="2026-08-10T00:00:00Z"
    )
    row = next(r for r in report.happened.not_claimable if r.outcome_id == OUTCOME_CAUSED)
    assert row.reason_category == "refused"
    assert row.refusal_capsule_id == refusal_id
    assert row.acknowledged is True
    assert row.acknowledgment_capsule_id == ack_id


def test_not_claimable_register_is_honest_about_an_unacknowledged_refusal(store, signer, pack):
    _seed_ledger(store, signer)
    _seed_refusal(store, signer, pack, acknowledge=False)
    report = build_period_report(
        store, pack, audience="auditor", since=None, until=None, generated_at="2026-08-10T00:00:00Z"
    )
    row = next(r for r in report.happened.not_claimable if r.outcome_id == OUTCOME_CAUSED)
    assert row.acknowledged is False
    assert row.acknowledgment_capsule_id is None


def test_deferral_register_ages_a_deferred_response(store, signer, pack):
    _seed_ledger(store, signer, ts="2026-08-01T00:00:00Z")
    report = build_period_report(
        store, pack, audience="auditor", since=None, until=None, generated_at="2026-08-03T00:00:00Z"
    )
    assert len(report.happened.deferrals) == 1
    row = report.happened.deferrals[0]
    assert row.offer_id == f"{OUTCOME_EXCHANGE}/3"
    assert row.age_label == "2d"


def test_report_capsule_cites_the_level_2_aggregates_it_renders(store, signer, pack):
    _seed_ledger(store, signer)
    _seed_refusal(store, signer, pack)
    report = build_period_report(
        store, pack, audience="auditor", since=None, until=None, generated_at="2026-08-10T00:00:00Z"
    )
    report_capsule = seal_period_report_capsule(report, operator=OPERATOR, developer=DEVELOPER, signer=signer)
    detail = report_capsule["asg_payload"]["detail"]
    assert set(detail["cited_capsule_ids"]) == set(report.cited_capsule_ids)
    # every cited id resolves to a real capsule this test actually appended
    for cid in detail["cited_capsule_ids"]:
        assert store.fetch(cid) is not None


def test_render_text_carries_no_reserved_verdict_word(store, signer, pack):
    _seed_ledger(store, signer)
    _seed_refusal(store, signer, pack)
    report = build_period_report(
        store, pack, audience="auditor", since=None, until=None, generated_at="2026-08-10T00:00:00Z"
    )
    text = render_text(report)
    lowered = text.lower()
    for word in RESERVED_VERDICT_WORDS:
        assert word not in lowered.split(), f"reserved verdict word {word!r} leaked into rendered report text"


def test_render_text_mutant_proof_deny_list_check_can_fail(store, signer, pack):
    """RED-before-green for the assertion above: prove it actually notices
    a reserved word if one is present, rather than trivially passing."""
    text = "this report is fully certified and guaranteed"
    lowered = text.lower()
    hit = any(word in lowered.split() for word in RESERVED_VERDICT_WORDS)
    assert hit, "the deny-list check itself failed to catch an obviously-reserved word"


def test_cli_report_end_to_end_offline_verifies_a_sampled_row_with_network_blocked(tmp_path, signer):
    from capsule_ledger.ledger import LedgerStore

    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    store = LedgerStore(ledger_dir)
    try:
        pack = load_pack_dir(PACK_DIR)
        _seed_ledger(store, signer)
        _seed_refusal(store, signer, pack)
    finally:
        store.close()

    out = tmp_path / "report.txt"
    rc = cli_main(
        [
            "report",
            "--pack", str(PACK_DIR),
            "--ledger", str(ledger_dir),
            "--audience", "auditor",
            "--out", str(out),
            "--key-id", "test-key-1",
            "--secret", "test-secret",
        ]
    )
    assert rc == 0
    assert out.exists()
    bundle_path = tmp_path / "report.bundle.json"
    assert bundle_path.exists()

    text = out.read_text(encoding="utf-8")
    assert "## 1. what was promised" in text
    assert "## 2. what happened" in text
    assert "## 3. can I check it" in text

    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert bundle["records"], "bundle must carry at least one record to sample"
    sample = bundle["records"][0]

    # The acceptance line: an auditor with only the report artifact and the
    # OSS verifier checks a sampled row offline, no network. Prove no
    # network I/O happens by making socket connections raise.
    def _no_network(*_args, **_kwargs):
        raise AssertionError("capsule verify attempted a network connection")

    original_connect = socket.socket.connect
    socket.socket.connect = _no_network  # type: ignore[method-assign]
    try:
        ids = [r["capsule_id"] for r in bundle["records"]]
        result = verify_capsule(sample, store=ids)
    finally:
        socket.socket.connect = original_connect  # type: ignore[method-assign]

    assert result.ok, f"sampled row failed to check out offline: {result.findings}"
