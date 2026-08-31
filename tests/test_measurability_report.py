# SPDX-License-Identifier: Apache-2.0
"""``[pack-propose-generic]``: the generic "would this pack work" report.

Same self-contained fixture convention as ``test_corpus_verify.py`` (no
``tests/__init__.py`` in this repo -- each test module duplicates its own
minimal pack scaffold rather than cross-importing another test module's).
"""
from __future__ import annotations

from pathlib import Path

import yaml

from capsule_ledger.packs.loader import load_pack_dir
from capsule_ledger.packs.measurability_report import (
    NOT_ENOUGH_REPEAT_TRAFFIC_DETAIL,
    STATUS_MISSING_INSTRUMENT,
    STATUS_NOT_ENOUGH_REPEAT_TRAFFIC,
    STATUS_RESOLVES,
    build_measurability_report,
    render_terminal,
)

AIRLINE_ENGAGEMENT_DIR = Path(__file__).parent.parent / "capsule_ledger" / "packs" / "catalog" / "airline-engagement"
STANDARD_VENDOR_DIR = Path(__file__).parent.parent / "capsule_ledger" / "packs" / "catalog" / "standard-vendor"

BASE_PACK = {
    "pack_id": "test_pub/test-pack/1.0.0",
    "obligations": [{"id": "o1", "statement": "no dup", "check": "dedupe"}],
    "action_semantics": [
        {"action_type": "payment.dispatch", "action_class": "money.transfer", "required_fields": ["amount_minor"]}
    ],
    "constraints": [{"wicket_id": "test.dedupe/1.0.0", "check": "dedupe", "config": {}}],
    "folds": [{"file": "spend.yaml"}],
}

MINIMAL_FOLD_YAML = """
fold_id: test.spend/1.0.0
reads:
  - path: developer
    erasure_class: commitment-ok
key: developer
reduce:
  reducer: count
emit: n
"""


def _outcome(**overrides) -> dict:
    base = {
        "id": "outcome.remediation_confirmed",
        "statement": "The flagged condition was remediated.",
        "evidence_rule": "fulfill capsule chained to intent, effect_attestation=counterparty_confirmed",
        "forward_verdict": "DETERMINISTIC",
        "backward_verdict": "DETERMINISTIC",
    }
    base.update(overrides)
    return base


def _write_pack(tmp_path: Path, overrides: dict | None = None) -> Path:
    data = {**BASE_PACK, **(overrides or {})}
    (tmp_path / "pack.yaml").write_text(yaml.dump(data))
    (tmp_path / "spend.yaml").write_text(MINIMAL_FOLD_YAML)
    return tmp_path


def _unit(messages: list[dict], **extra) -> dict:
    return {"messages": messages, **extra}


def _by_id(rows, outcome_id):
    return next(r for r in rows if r.outcome_id == outcome_id)


# --- structural/judged/value rows -- same resolve-check as corpus_verify ---


def test_structural_row_with_no_instrument_anywhere_reports_missing_instrument(tmp_path):
    pack_dir = _write_pack(
        tmp_path,
        {
            "outcomes": [
                _outcome(
                    id="outcome.needs_typed_field",
                    mode="structural",
                    measurability="declared_not_measured",
                    forward_verdict="UNAVAILABLE-STATE-REQUIRED",
                    evidence_instrument={"kind": "structured_field", "field": "restriction_reason_cited"},
                )
            ]
        },
    )
    pack = load_pack_dir(pack_dir)
    corpus = [_unit([{"role": "user", "content": "hi", "tool_call_names": []}])]
    report = build_measurability_report(pack, corpus, entity_key=lambda u: id(u))

    row = _by_id(report, "outcome.needs_typed_field")
    assert row.status == STATUS_MISSING_INSTRUMENT
    assert row.mode == "structural"
    assert row.core_definition_digest is None  # not a fold mode -- no digest expected


def test_structural_row_resolves_when_the_field_is_present(tmp_path):
    pack_dir = _write_pack(
        tmp_path,
        {
            "outcomes": [
                _outcome(
                    id="outcome.needs_typed_field",
                    mode="structural",
                    measurability="declared_not_measured",
                    forward_verdict="UNAVAILABLE-STATE-REQUIRED",
                    evidence_instrument={"kind": "structured_field", "field": "restriction_reason_cited"},
                )
            ]
        },
    )
    pack = load_pack_dir(pack_dir)
    corpus = [_unit([{"role": "assistant", "content": "x", "tool_call_names": [], "restriction_reason_cited": "fare-14.2"}])]
    report = build_measurability_report(pack, corpus, entity_key=lambda u: id(u))
    assert _by_id(report, "outcome.needs_typed_field").status == STATUS_RESOLVES


def test_a_measured_row_with_no_instrument_reports_resolves_not_a_gap(tmp_path):
    """A real, already-measured row (measurability defaults to 'measured',
    no evidence_instrument declared) has no instrumentation gap to report
    -- distinct from a declared_not_measured row that's missing its signal."""
    pack_dir = _write_pack(tmp_path, {"outcomes": [_outcome(id="outcome.already_measured", mode="judged")]})
    pack = load_pack_dir(pack_dir)
    report = build_measurability_report(pack, [], entity_key=lambda u: id(u))
    row = _by_id(report, "outcome.already_measured")
    assert row.status == STATUS_RESOLVES
    assert "not a declared-not-measured row" in row.detail


# --- Stage 1b [LOCKED]: fold_counterparty/fold_cohort repeat-traffic gate --


def _fold_counterparty_pack(tmp_path: Path):
    pack_dir = _write_pack(
        tmp_path,
        {
            "outcomes": [
                _outcome(
                    id="outcome.capability_growth",
                    mode="fold_counterparty",
                    tier="informational",
                    measurability="declared_not_measured",
                    forward_verdict="UNAVAILABLE-STATE-REQUIRED",
                    evidence_instrument={"kind": "structured_field", "field": "basic_question_count_trend"},
                )
            ]
        },
    )
    return load_pack_dir(pack_dir)


def test_fold_counterparty_reports_not_enough_repeat_traffic_when_every_unit_is_a_different_entity(tmp_path):
    pack = _fold_counterparty_pack(tmp_path)
    corpus = [_unit([{"role": "user", "content": "a"}]), _unit([{"role": "user", "content": "b"}])]
    report = build_measurability_report(pack, corpus, entity_key=lambda u: id(u))  # id() differs per dict -> no repeats
    row = _by_id(report, "outcome.capability_growth")
    assert row.status == STATUS_NOT_ENOUGH_REPEAT_TRAFFIC
    assert row.detail == NOT_ENOUGH_REPEAT_TRAFFIC_DETAIL  # exact locked wording, not paraphrased
    assert row.core_definition_digest is not None  # still real -- the row isn't excluded, just honestly gated


def test_fold_counterparty_row_is_never_silently_excluded_from_the_report(tmp_path):
    """The report's own row count must include Stage-1b-gated rows -- the
    lock explicitly forbids silent exclusion, not just a specific string."""
    pack = _fold_counterparty_pack(tmp_path)
    corpus = [_unit([{"role": "user", "content": "a"}])]
    report = build_measurability_report(pack, corpus, entity_key=lambda u: id(u))
    assert len(report) == 1
    assert report[0].outcome_id == "outcome.capability_growth"


def test_fold_counterparty_falls_through_to_the_instrument_check_when_repeat_traffic_exists(tmp_path):
    pack = _fold_counterparty_pack(tmp_path)
    corpus = [_unit([{"role": "user", "content": "a"}]), _unit([{"role": "user", "content": "b"}])]
    report = build_measurability_report(pack, corpus, entity_key=lambda u: "same-customer")
    row = _by_id(report, "outcome.capability_growth")
    assert row.status == STATUS_MISSING_INSTRUMENT  # repeat traffic present, but the field still never resolves
    assert row.core_definition_digest is not None


def test_fold_rollup_and_fold_agent_are_not_repeat_traffic_gated(tmp_path):
    """Only fold_counterparty/fold_cohort are named in the Stage-1b lock --
    fold_rollup/fold_agent go through the plain instrument check, still with
    a digest through the seam."""
    pack_dir = _write_pack(
        tmp_path,
        {
            "outcomes": [
                _outcome(id="outcome.session_rollup", mode="fold_rollup"),
                _outcome(
                    id="outcome.agent_trend", mode="fold_agent", measurability="declared_not_measured",
                    forward_verdict="UNAVAILABLE-STATE-REQUIRED",
                    evidence_instrument={"kind": "structured_field", "field": "must_have_rate_trend"},
                ),
            ]
        },
    )
    pack = load_pack_dir(pack_dir)
    corpus = [_unit([{"role": "user", "content": "a"}])]  # single unit -- would fail a repeat-traffic gate if applied
    report = build_measurability_report(pack, corpus, entity_key=lambda u: id(u))

    rollup = _by_id(report, "outcome.session_rollup")
    assert rollup.status == STATUS_RESOLVES  # no instrument declared -- not a gap
    assert rollup.core_definition_digest is not None

    agent = _by_id(report, "outcome.agent_trend")
    assert agent.status == STATUS_MISSING_INSTRUMENT  # NOT not_enough_repeat_traffic
    assert agent.core_definition_digest is not None


# --- the unified fold seam: real digest, not a report-local one ------------


def test_fold_mode_digest_comes_from_the_real_seam_not_a_second_implementation():
    """Grep-gate-style proof: independently project the SAME outcome onto a
    FoldDefinition and read core_definition_digest() directly -- if the
    report ever grew its own digest logic instead of routing through
    folds/account_core.py, this would catch the divergence."""
    from capsule_ledger.folds import DERIVATION_DETERMINISTIC, FoldDefinition, ReadField, Reduce

    pack_dir_data = {**BASE_PACK, "outcomes": [_outcome(id="outcome.rollup_only", mode="fold_rollup")]}

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "pack.yaml").write_text(yaml.dump(pack_dir_data))
        (tmp_path / "spend.yaml").write_text(MINIMAL_FOLD_YAML)
        pack = load_pack_dir(tmp_path)

    report = build_measurability_report(pack, [], entity_key=lambda u: id(u))
    row = _by_id(report, "outcome.rollup_only")

    independent = FoldDefinition(
        fold_id="measurability_report.outcome.rollup_only/1.0.0",
        reads=(ReadField(path="outcome.rollup_only", erasure_class="commitment-ok"),),
        reduce=Reduce(reducer="count"),
        emit="outcome.rollup_only.fold_rollup.measurability",
        derivation_class=DERIVATION_DETERMINISTIC,
    )
    assert row.core_definition_digest == independent.core_definition_digest()


def test_judged_mode_fold_digest_uses_model_assisted_derivation_class():
    pack_dir_data = {**BASE_PACK, "outcomes": [_outcome(id="outcome.judged_fold", mode="fold_counterparty")]}
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "pack.yaml").write_text(yaml.dump(pack_dir_data))
        (tmp_path / "spend.yaml").write_text(MINIMAL_FOLD_YAML)
        pack = load_pack_dir(tmp_path)

    outcome = pack.outcome_for_id("outcome.judged_fold")
    assert outcome.mode == "fold_counterparty"  # deterministic class expected (not "judged")

    pack_dir_data2 = {**BASE_PACK, "outcomes": [_outcome(id="outcome.judged_row", mode="judged")]}
    with tempfile.TemporaryDirectory() as tmp2:
        tmp_path2 = Path(tmp2)
        (tmp_path2 / "pack.yaml").write_text(yaml.dump(pack_dir_data2))
        (tmp_path2 / "spend.yaml").write_text(MINIMAL_FOLD_YAML)
        pack2 = load_pack_dir(tmp_path2)
    # judged mode alone (not a fold mode) carries no digest at all -- only
    # fold-mode rows route through the seam.
    report2 = build_measurability_report(pack2, [], entity_key=lambda u: id(u))
    assert _by_id(report2, "outcome.judged_row").core_definition_digest is None


# --- entity_key is required -------------------------------------------------


def test_entity_key_is_a_required_keyword_argument():
    import inspect

    sig = inspect.signature(build_measurability_report)
    assert sig.parameters["entity_key"].default is inspect.Parameter.empty


# --- the real committed packs (regression + the actual target) -------------


def test_the_real_standard_vendor_pack_produces_a_row_for_every_outcome_unregressed():
    pack = load_pack_dir(STANDARD_VENDOR_DIR)
    corpus = [_unit([{"role": "user", "content": "hi", "tool_call_names": []}])]
    report = build_measurability_report(pack, corpus, entity_key=lambda u: id(u))
    assert len(report) == len(pack.outcomes) == 22
    assert {r.outcome_id for r in report} == {o.id for o in pack.outcomes}
    # every fold-mode row carries a digest; no non-fold row does
    fold_modes = {"fold_rollup", "fold_counterparty", "fold_agent", "fold_cohort"}
    for row in report:
        if row.mode in fold_modes:
            assert row.core_definition_digest is not None, row.outcome_id
        else:
            assert row.core_definition_digest is None, row.outcome_id
    # render_terminal must not raise on the real pack
    text = render_terminal(report)
    assert "S1" in text and "C1" in text and "X1" in text


def test_the_real_airline_engagement_pack_is_unregressed_by_this_new_module():
    """The airline pack has no fold-mode rows at all (A1-A7 are structural/
    judged) -- this proves the new module doesn't require fold-mode rows to
    function, and that adding this module didn't change airline's own
    (still airline-specific) propose path at all."""
    pack = load_pack_dir(AIRLINE_ENGAGEMENT_DIR)
    corpus = [_unit([{"role": "user", "content": "I need to change my flight", "tool_call_names": []}])]
    report = build_measurability_report(pack, corpus, entity_key=lambda u: id(u))
    assert len(report) == len(pack.outcomes)
    assert all(row.core_definition_digest is None for row in report)  # no fold modes in this pack
