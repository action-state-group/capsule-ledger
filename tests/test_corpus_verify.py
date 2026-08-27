# SPDX-License-Identifier: Apache-2.0
"""``corpus_verify.verify_declared_not_measured`` -- the oracle that proves a
``measurability: declared_not_measured`` claim rather than trusting it (see
``adv-tau2-demo.md`` Area 1/4, ``corpus_verify.py``'s module docstring).

Every negative case is exercised as a real RED/GREEN pair against the same
corpus construction: a corpus where the declared signal is absent (must
verify clean) and the SAME corpus with one unit mutated to carry that signal
(must raise) -- proving the check actually discriminates, not merely never
firing.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from capsule_ledger.packs.errors import CorpusVerificationError
from capsule_ledger.packs.loader import load_pack_dir

AIRLINE_ENGAGEMENT_DIR = Path(__file__).parent.parent / "capsule_ledger" / "packs" / "catalog" / "airline-engagement"

# Same minimal scaffold as test_pack_outcomes_schema.py's BASE_PACK/
# MINIMAL_FOLD_YAML/_outcome -- duplicated rather than cross-imported
# (test modules in this repo are each self-contained; there is no
# tests/__init__.py making them a package).
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


def _declared_not_measured_pack(tmp_path: Path, *, field: str = "restriction_reason_cited"):
    pack_dir = _write_pack(
        tmp_path,
        {
            "outcomes": [
                _outcome(
                    id="outcome.needs_typed_field",
                    measurability="declared_not_measured",
                    forward_verdict="UNAVAILABLE-STATE-REQUIRED",
                    evidence_instrument={"kind": "structured_field", "field": field},
                )
            ]
        },
    )
    return load_pack_dir(pack_dir)


def _unit(messages: list[dict]) -> dict:
    return {"messages": messages}


# --- structured_field -------------------------------------------------


def test_declared_not_measured_verifies_clean_when_the_field_never_appears(tmp_path):
    from capsule_ledger.packs.corpus_verify import verify_declared_not_measured

    pack = _declared_not_measured_pack(tmp_path)
    corpus = [
        _unit([{"role": "user", "content": "my flight is delayed", "tool_call_names": []}]),
        _unit([{"role": "assistant", "content": "let me check that", "tool_call_names": ["search_flights"]}]),
    ]
    verify_declared_not_measured(pack, corpus)  # must not raise


def test_declared_not_measured_raises_the_moment_the_field_is_present_anywhere(tmp_path):
    """The RED case this whole module exists to catch: the SAME corpus as
    the clean test above, but one unit's message now carries the declared
    field with a real value -- exactly what a future producer emitting the
    "missing" typed record would look like. Before this task, nothing would
    have noticed; a hardcoded ``always_false`` lambda would have kept
    reporting this term as inapplicable regardless."""
    from capsule_ledger.packs.corpus_verify import verify_declared_not_measured

    pack = _declared_not_measured_pack(tmp_path)
    corpus = [
        _unit([{"role": "user", "content": "my flight is delayed", "tool_call_names": []}]),
        _unit(
            [
                {
                    "role": "assistant",
                    "content": "the fare rule requires...",
                    "tool_call_names": [],
                    "restriction_reason_cited": "fare-rule-14.2",
                }
            ]
        ),
    ]
    with pytest.raises(CorpusVerificationError) as exc:
        verify_declared_not_measured(pack, corpus)
    assert exc.value.reason == "declared_not_measured_evidence_resolved"
    assert "outcome.needs_typed_field" in str(exc.value)


def test_an_empty_or_falsy_field_value_does_not_count_as_resolved(tmp_path):
    """A structured_field instrument checks for a REAL value, not merely key
    presence -- a message dict carrying the key with an empty string/list is
    not evidence the corpus actually emits this record."""
    from capsule_ledger.packs.corpus_verify import verify_declared_not_measured

    pack = _declared_not_measured_pack(tmp_path)
    corpus = [_unit([{"role": "user", "content": "hi", "tool_call_names": [], "restriction_reason_cited": ""}])]
    verify_declared_not_measured(pack, corpus)  # must not raise


def test_base_message_fields_are_never_treated_as_the_declared_instrument(tmp_path):
    """A pack author mistakenly naming a base schema field (content, role,
    tool_call_names) as the missing instrument would trivially "resolve" on
    every unit and prove nothing -- refused as a no-op, not silently
    accepted as a real check."""
    from capsule_ledger.packs.corpus_verify import verify_declared_not_measured

    pack = _declared_not_measured_pack(tmp_path, field="content")
    corpus = [_unit([{"role": "user", "content": "definitely non-empty", "tool_call_names": []}])]
    verify_declared_not_measured(pack, corpus)  # must not raise -- "content" is a base field, never the instrument


# --- tool_call_name -----------------------------------------------------


def test_tool_call_name_instrument_verifies_clean_when_the_call_never_appears(tmp_path):
    from capsule_ledger.packs.corpus_verify import verify_declared_not_measured

    pack_dir = _write_pack(
        tmp_path,
        {
            "outcomes": [
                _outcome(
                    id="outcome.needs_tool_call",
                    measurability="declared_not_measured",
                    forward_verdict="UNAVAILABLE-STATE-REQUIRED",
                    evidence_instrument={"kind": "tool_call_name", "name": "issue_refund"},
                )
            ]
        },
    )
    pack = load_pack_dir(pack_dir)
    corpus = [_unit([{"role": "assistant", "content": "", "tool_call_names": ["search_flights"]}])]
    verify_declared_not_measured(pack, corpus)


def test_tool_call_name_instrument_raises_when_the_call_appears(tmp_path):
    from capsule_ledger.packs.corpus_verify import verify_declared_not_measured

    pack_dir = _write_pack(
        tmp_path,
        {
            "outcomes": [
                _outcome(
                    id="outcome.needs_tool_call",
                    measurability="declared_not_measured",
                    forward_verdict="UNAVAILABLE-STATE-REQUIRED",
                    evidence_instrument={"kind": "tool_call_name", "name": "issue_refund"},
                )
            ]
        },
    )
    pack = load_pack_dir(pack_dir)
    corpus = [_unit([{"role": "assistant", "content": "", "tool_call_names": ["search_flights", "issue_refund"]}])]
    with pytest.raises(CorpusVerificationError):
        verify_declared_not_measured(pack, corpus)


# --- measured-only packs / no-op ----------------------------------------


def test_a_pack_with_no_declared_not_measured_outcomes_never_scans_the_corpus(tmp_path):
    """No declared_not_measured outcomes -> nothing to check -> a corpus
    argument that would explode if iterated proves the function short-
    circuits rather than pointlessly scanning."""
    from capsule_ledger.packs.corpus_verify import verify_declared_not_measured

    pack_dir = _write_pack(tmp_path, {"outcomes": [_outcome()]})
    pack = load_pack_dir(pack_dir)

    def _exploding_corpus():
        raise AssertionError("must not be iterated")
        yield {}  # pragma: no cover

    verify_declared_not_measured(pack, _exploding_corpus())


# --- the real committed airline-engagement pack -------------------------


def test_the_real_airline_engagement_pack_verifies_clean_on_a_tau2_shaped_corpus_with_no_typed_fields():
    """The real catalog pack's three declared_not_measured rows
    (A2/A3a/A5) against a corpus shaped exactly like
    ``record_grounding_bench.judge_run.transcript.Sim.to_dict()`` output
    (only role/content/tool_call_names ever present) -- this is the actual
    invariant the tau2 airline demo relies on."""
    from capsule_ledger.packs.corpus_verify import verify_declared_not_measured

    pack = load_pack_dir(AIRLINE_ENGAGEMENT_DIR)
    corpus = [
        _unit(
            [
                {"role": "user", "content": "I need to change my flight", "tool_call_names": []},
                {"role": "assistant", "content": "you can change to an earlier flight or a later one", "tool_call_names": []},
            ]
        ),
    ]
    verify_declared_not_measured(pack, corpus)


def test_the_real_airline_engagement_pack_raises_if_a_future_corpus_started_emitting_the_typed_field():
    """The RED proof against the real catalog pack, not just a synthetic
    fixture: if a future corpus producer started emitting one of the three
    named typed fields, this must be caught, not silently rendered as
    'inapplicable' the way the old hardcoded lambda would have."""
    from capsule_ledger.packs.corpus_verify import verify_declared_not_measured

    pack = load_pack_dir(AIRLINE_ENGAGEMENT_DIR)
    corpus = [
        _unit(
            [
                {
                    "role": "assistant",
                    "content": "per policy...",
                    "tool_call_names": [],
                    "typed_severity_efficacy_label": "high-severity/high-efficacy",
                }
            ]
        ),
    ]
    with pytest.raises(CorpusVerificationError) as exc:
        verify_declared_not_measured(pack, corpus)
    assert "A3a" in str(exc.value)
