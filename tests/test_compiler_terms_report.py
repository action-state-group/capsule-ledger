# SPDX-License-Identifier: Apache-2.0
"""The fold-based terms report renderer (terms-to-report design §3).
Load-bearing properties, each with a named test:

1. Epoch partition by ``c_digest`` never blends -- two verdict batches
   compiled under different ``c_digest``s (a renegotiation) render as two
   separate lines, each with its own counts, never summed together.
2. Every rendered line carries a fold envelope naming ``f_digest``/range/
   checkpoint root/as_of/epoch.
3. ``clause_ref`` is the provenance column, present on both report lines
   and refusal rows.
4. Refusal rows render (not dropped), with their reason code.
5. Same-family-judge caveat renders when two epochs sharing a term line
   share a judge family.
6. Self-seeded-sampler caveat (chunk 4) renders when supplied via
   ``epoch_caveats``.
7. Per-epoch lines never blend -- two epochs judging the same c_digest
   render as two lines, each with its own counts.
8. Sampled-mode sampling rate (chunk 4's sampler) renders in the fold
   envelope when supplied via ``epoch_sampling_rates``; a line for which no
   rate was supplied never fabricates one.
"""
from __future__ import annotations

from capsule_ledger.compiler.compile import Declaration
from capsule_ledger.compiler.epoch_registry import EpochOpen
from capsule_ledger.compiler.terms_desk import (
    ApplicabilitySpec,
    JudgeOrRuleSpec,
    TermDeclaration,
    compile_term,
    compiled_term_digest,
)
from capsule_ledger.compiler.terms_report import render_terms_report
from capsule_ledger.guards import LocalSigner
from capsule_ledger.guards.capsule import build_event_capsule

OPERATOR = "test-operator"
DEVELOPER = "test-developer@v1"
T_DIGEST = "a" * 64

_signer = LocalSigner(key_id="report-test-key", secret=b"report-test-secret")


def _judged_term(term_id: str = "term.judged_care", clause_ref: str | None = "contract/§7.1"):
    declaration = Declaration(
        outcome_id=term_id,
        statement="escalations are acknowledged within one business day",
        requires_model_judgment=True,
    )
    term = TermDeclaration(
        term_id=term_id,
        statement=declaration.statement,
        clause_ref=clause_ref,
        applicability=ApplicabilitySpec(unit="turn"),
        verdict_schema=("pass", "fail"),
        declaration=declaration,
        judge_spec=JudgeOrRuleSpec(
            kind="judge", verdict_schema=("pass", "fail"), model_id="judge-model-x@1", prompt_digest="p" * 64
        ),
    )
    return compile_term(term)


def _refused_term(term_id: str = "term.refused", clause_ref: str | None = "contract/§9.9"):
    declaration = Declaration(
        outcome_id=term_id,
        statement="the interaction increased trust",
        effect_claim="agent.caused_resolution",
    )
    term = TermDeclaration(
        term_id=term_id,
        statement=declaration.statement,
        clause_ref=clause_ref,
        applicability=ApplicabilitySpec(unit="turn"),
        verdict_schema=("pass", "fail"),
        declaration=declaration,
    )
    return compile_term(term)


def _deterministic_term(term_id: str = "term.direct_deterministic", clause_ref: str | None = "contract/§3.1"):
    declaration = Declaration(
        outcome_id=term_id,
        statement="a direct declaration, forward-compiled",
        allowed_actions=("remediation",),
        binding={"action_class": "remediation"},
    )
    term = TermDeclaration(
        term_id=term_id,
        statement=declaration.statement,
        clause_ref=clause_ref,
        applicability=ApplicabilitySpec(unit="turn"),
        verdict_schema=("pass", "fail"),
        declaration=declaration,
    )
    return compile_term(term)


def _verdict_record(*, term_id: str, c_digest: str, epoch: str, verdict: str, applicable: bool = True, subject_id: str = "1" * 64):
    detail = {
        "subject": {"capsule_id": subject_id, "digest": "d" * 64},
        "term": {"term_id": term_id, "c_digest": c_digest, "j_digest": "j" * 64},
        "applicable": applicable,
        "verdict": verdict,
        "abstain_reason": "insufficient_evidence" if (verdict == "ABSTAIN" and applicable) else None,
        "basis": {"evidence_digests": []},
        "judge_pin": None,
        "epoch": epoch,
        "ext": {"tokens_in": None, "tokens_out": None, "cost_minor": None},
    }
    return build_event_capsule(
        operator=OPERATOR,
        developer=DEVELOPER,
        signer=_signer,
        event="judge_agent_verdict",
        detail=detail,
        chain_parent=subject_id,
        chain_relation="assesses",
    )


# --- 1. partition by c_digest never blends ----------------------------------


def test_renegotiated_term_renders_two_lines_never_blended():
    ct = _judged_term()
    c_digest_v1 = "1" * 64
    c_digest_v2 = "2" * 64
    records = [
        _verdict_record(term_id=ct.term_id, c_digest=c_digest_v1, epoch="epoch-a", verdict="pass"),
        _verdict_record(term_id=ct.term_id, c_digest=c_digest_v1, epoch="epoch-a", verdict="pass"),
        _verdict_record(term_id=ct.term_id, c_digest=c_digest_v2, epoch="epoch-a", verdict="fail"),
    ]
    report = render_terms_report((ct,), records)
    assert len(report.lines) == 2
    by_c_digest = {line.c_digest: line for line in report.lines}
    assert by_c_digest[c_digest_v1].verdict_counts == {"pass": 2}
    assert by_c_digest[c_digest_v2].verdict_counts == {"fail": 1}
    # never blended: v1's count is untouched by v2's row and vice versa
    assert by_c_digest[c_digest_v1].applicable_n == 2
    assert by_c_digest[c_digest_v2].applicable_n == 1


# --- 2. fold envelope on every number ---------------------------------------


def test_every_line_carries_a_fold_envelope():
    ct = _judged_term()
    c_digest = compiled_term_digest(ct)
    records = [_verdict_record(term_id=ct.term_id, c_digest=c_digest, epoch="epoch-a", verdict="pass")]
    report = render_terms_report((ct,), records, range_start=5, as_of="2026-08-26T00:00:00Z", checkpoint_root="root123")
    assert len(report.lines) == 1
    envelope = report.lines[0].envelope
    assert envelope.f_digest == ct.f_digest
    assert envelope.range_start == 5
    assert envelope.range_end == 5
    assert envelope.checkpoint_root == "root123"
    assert envelope.as_of == "2026-08-26T00:00:00Z"
    assert envelope.epoch == "epoch-a"


def test_deterministic_term_line_also_carries_a_fold_envelope():
    ct = _deterministic_term()
    records = [
        {"developer": DEVELOPER, "disposition": {"verdict_class": "executed"}, "asg_payload": {"action_class": "remediation"}},
    ]
    report = render_terms_report((ct,), records, checkpoint_root="root456")
    assert len(report.lines) == 1
    envelope = report.lines[0].envelope
    assert envelope.f_digest == ct.f_digest
    assert envelope.checkpoint_root == "root456"
    assert envelope.epoch is None
    # a full-census/unsampled line (no judge epoch at all) must never
    # fabricate a sampling rate
    assert envelope.sampling_rate is None


# --- 3. clause_ref provenance column ----------------------------------------


def test_clause_ref_carried_on_report_lines():
    ct = _judged_term(clause_ref="contract/§7.1")
    c_digest = compiled_term_digest(ct)
    records = [_verdict_record(term_id=ct.term_id, c_digest=c_digest, epoch="epoch-a", verdict="pass")]
    report = render_terms_report((ct,), records)
    assert report.lines[0].clause_ref == "contract/§7.1"


def test_clause_ref_carried_on_refusal_rows():
    ct = _refused_term(clause_ref="contract/§9.9")
    report = render_terms_report((ct,), records=[])
    assert len(report.refusals) == 1
    assert report.refusals[0].clause_ref == "contract/§9.9"


# --- 4. refusal rows render --------------------------------------------------


def test_refusal_rows_render_with_reason_code_and_are_not_dropped():
    refused = _refused_term()
    judged = _judged_term()
    c_digest = compiled_term_digest(judged)
    records = [_verdict_record(term_id=judged.term_id, c_digest=c_digest, epoch="epoch-a", verdict="pass")]
    report = render_terms_report((refused, judged), records)
    assert len(report.refusals) == 1
    assert report.refusals[0].term_id == "term.refused"
    assert report.refusals[0].reason_code == "agent_caused_resolution_undecomposable"
    # the refused term contributes no report line
    assert all(line.term_id != "term.refused" for line in report.lines)
    # but the judged term's line still renders alongside it
    assert any(line.term_id == "term.judged_care" for line in report.lines)


# --- 5. same-family-judge caveat --------------------------------------------


def test_same_family_caveat_renders_when_two_epochs_share_judge_family():
    ct = _judged_term()
    c_digest = compiled_term_digest(ct)
    records = [
        _verdict_record(term_id=ct.term_id, c_digest=c_digest, epoch="epoch-a", verdict="pass"),
        _verdict_record(term_id=ct.term_id, c_digest=c_digest, epoch="epoch-b", verdict="fail"),
    ]
    epoch_opens = (
        EpochOpen(epoch_id="epoch-a", opened_at="t1", t_digest=T_DIGEST, judge_family="openai"),
        EpochOpen(epoch_id="epoch-b", opened_at="t2", t_digest=T_DIGEST, judge_family="openai"),
    )
    report = render_terms_report((ct,), records, epoch_opens=epoch_opens)
    by_epoch = {line.epoch: line for line in report.lines}
    assert any(c.get("caveat") == "same_family_judging" for c in by_epoch["epoch-a"].caveats)
    assert any(c.get("caveat") == "same_family_judging" for c in by_epoch["epoch-b"].caveats)


def test_no_same_family_caveat_when_judge_families_differ():
    ct = _judged_term()
    c_digest = compiled_term_digest(ct)
    records = [
        _verdict_record(term_id=ct.term_id, c_digest=c_digest, epoch="epoch-a", verdict="pass"),
        _verdict_record(term_id=ct.term_id, c_digest=c_digest, epoch="epoch-b", verdict="fail"),
    ]
    epoch_opens = (
        EpochOpen(epoch_id="epoch-a", opened_at="t1", t_digest=T_DIGEST, judge_family="openai"),
        EpochOpen(epoch_id="epoch-b", opened_at="t2", t_digest=T_DIGEST, judge_family="anthropic"),
    )
    report = render_terms_report((ct,), records, epoch_opens=epoch_opens)
    for line in report.lines:
        assert all(c.get("caveat") != "same_family_judging" for c in line.caveats)


# --- 6. self-seeded sampler caveat (chunk 4) --------------------------------


def test_self_seeded_caveat_from_chunk4_renders_on_the_matching_epoch_line():
    ct = _judged_term()
    c_digest = compiled_term_digest(ct)
    records = [
        _verdict_record(term_id=ct.term_id, c_digest=c_digest, epoch="epoch-a", verdict="pass"),
        _verdict_record(term_id=ct.term_id, c_digest=c_digest, epoch="epoch-b", verdict="fail"),
    ]
    self_seeded_caveat = {
        "caveat": "self_seeded_adjudication_sample",
        "detail": "no external entropy source was available for this run.",
    }
    report = render_terms_report((ct,), records, epoch_caveats={"epoch-a": (self_seeded_caveat,)})
    by_epoch = {line.epoch: line for line in report.lines}
    assert self_seeded_caveat in by_epoch["epoch-a"].caveats
    assert self_seeded_caveat not in by_epoch["epoch-b"].caveats


# --- 7. per-epoch lines never blended ----------------------------------------


def test_two_epochs_over_the_same_c_digest_render_as_separate_unblended_lines():
    ct = _judged_term()
    c_digest = compiled_term_digest(ct)
    records = [
        _verdict_record(term_id=ct.term_id, c_digest=c_digest, epoch="epoch-a", verdict="pass"),
        _verdict_record(term_id=ct.term_id, c_digest=c_digest, epoch="epoch-a", verdict="pass"),
        _verdict_record(term_id=ct.term_id, c_digest=c_digest, epoch="epoch-a", verdict="fail"),
        _verdict_record(term_id=ct.term_id, c_digest=c_digest, epoch="epoch-b", verdict="fail"),
    ]
    report = render_terms_report((ct,), records)
    assert len(report.lines) == 2
    by_epoch = {line.epoch: line for line in report.lines}
    assert by_epoch["epoch-a"].verdict_counts == {"pass": 2, "fail": 1}
    assert by_epoch["epoch-b"].verdict_counts == {"fail": 1}
    # never blended: epoch-a's fail count is not contaminated by epoch-b's
    assert by_epoch["epoch-a"].applicable_n == 3
    assert by_epoch["epoch-b"].applicable_n == 1


# --- paired metrics: coverage always ships with its denominator ------------


def test_coverage_is_a_paired_n_m_and_abstain_never_counted_as_judged():
    ct = _judged_term()
    c_digest = compiled_term_digest(ct)
    records = [
        _verdict_record(term_id=ct.term_id, c_digest=c_digest, epoch="epoch-a", verdict="pass"),
        _verdict_record(term_id=ct.term_id, c_digest=c_digest, epoch="epoch-a", verdict="ABSTAIN"),
        _verdict_record(term_id=ct.term_id, c_digest=c_digest, epoch="epoch-a", verdict="ABSTAIN", applicable=False),
    ]
    report = render_terms_report((ct,), records)
    line = report.lines[0]
    assert line.applicable_n == 2  # the inapplicable row is excluded
    assert line.inapplicable_n == 1
    assert line.units_in_range == 3
    assert line.coverage_n == 1  # 2 applicable minus 1 ABSTAIN
    assert line.coverage_m == 3


# --- inapplicable rows are visible (denominator), not dropped --------------


def test_inapplicable_rows_are_counted_not_dropped():
    ct = _judged_term()
    c_digest = compiled_term_digest(ct)
    records = [
        _verdict_record(term_id=ct.term_id, c_digest=c_digest, epoch="epoch-a", verdict="pass"),
        _verdict_record(term_id=ct.term_id, c_digest=c_digest, epoch="epoch-a", verdict="ABSTAIN", applicable=False, subject_id="2"*64),
        _verdict_record(term_id=ct.term_id, c_digest=c_digest, epoch="epoch-a", verdict="ABSTAIN", applicable=False, subject_id="3"*64),
    ]
    report = render_terms_report((ct,), records)
    line = report.lines[0]
    assert line.inapplicable_n == 2
    assert line.units_in_range == 3


# --- Attack 4 (adversarial pass, launch-blocker): silently dropped units ---
# must not be invisible to coverage. `units_in_range` built purely from
# sealed verdict rows reads n/n = 100% even when the run-summary capsule's
# committed population is larger -- the honest denominator that already
# exists (`RunSummaryCounts.units_in_range`, sealed in the
# EVENT_RUN_SUMMARY capsule) must be consulted and any disagreement made
# visible, not silently resolved by trusting the verdict rows alone.


def _run_summary_record(*, epoch: str, units_in_range: int):
    detail = {
        "range": {"checkpoint_prev": None, "checkpoint_close": {"mmr_size": 10, "root": "r" * 64}},
        "epoch": epoch,
        "grace_window_minutes": 2880,
        "units_in_range": units_in_range,
        "verdicts_emitted": units_in_range,
        "abstentions": 0,
        "abstain_rate_per_term_micros": {},
        "units_skipped": [],
        "open_units": 0,
    }
    return build_event_capsule(
        operator=OPERATOR,
        developer=DEVELOPER,
        signer=_signer,
        event="judge_agent_run_summary",
        detail=detail,
        action_id=f"judge_agent.run_summary/{epoch}",
    )


def test_silently_dropped_units_surface_as_a_visible_coverage_discrepancy():
    """Attack 4 repro: 10 subjects were in the run-summary's committed
    population for this epoch, but only 2 carry verdict rows for the term
    under test (the other 8 were silently dropped, e.g. by a mid-run
    crash). The verdict-row-derived count alone reads 2/2 == 100% coverage
    -- the bug. Cross-checking against the run-summary's `units_in_range`
    must surface the gap instead of hiding it."""
    ct = _judged_term()
    c_digest = compiled_term_digest(ct)
    records = [
        _verdict_record(term_id=ct.term_id, c_digest=c_digest, epoch="epoch-a", verdict="pass", subject_id="1" * 64),
        _verdict_record(term_id=ct.term_id, c_digest=c_digest, epoch="epoch-a", verdict="fail", subject_id="2" * 64),
        _run_summary_record(epoch="epoch-a", units_in_range=10),
    ]
    report = render_terms_report((ct,), records)
    line = report.lines[0]
    # the row-derived count alone (the pre-fix behavior) is 2 -- this stays
    # visible as its own field, never silently discarded
    assert line.verdict_rows_n == 2
    # the honest denominator is the run-summary's committed population
    assert line.units_in_range == 10
    assert line.coverage_discrepancy is True
    assert any(c.get("caveat") == "coverage_discrepancy" for c in line.caveats)


def test_matching_run_summary_renders_no_discrepancy():
    ct = _judged_term()
    c_digest = compiled_term_digest(ct)
    records = [
        _verdict_record(term_id=ct.term_id, c_digest=c_digest, epoch="epoch-a", verdict="pass", subject_id="1" * 64),
        _verdict_record(term_id=ct.term_id, c_digest=c_digest, epoch="epoch-a", verdict="fail", subject_id="2" * 64),
        _run_summary_record(epoch="epoch-a", units_in_range=2),
    ]
    report = render_terms_report((ct,), records)
    line = report.lines[0]
    assert line.verdict_rows_n == 2
    assert line.units_in_range == 2
    assert line.coverage_discrepancy is False
    assert all(c.get("caveat") != "coverage_discrepancy" for c in line.caveats)


def test_no_run_summary_present_falls_back_to_verdict_rows_without_a_fabricated_discrepancy():
    """When no run-summary capsule exists for the epoch at all (e.g. an
    older ledger, or a report run before chunk 6 wires up the daily
    orchestrator), there is no independent population to cross-check
    against -- fall back to the verdict-row-derived count exactly as
    before, and never claim a discrepancy with a number that isn't
    actually there."""
    ct = _judged_term()
    c_digest = compiled_term_digest(ct)
    records = [
        _verdict_record(term_id=ct.term_id, c_digest=c_digest, epoch="epoch-a", verdict="pass", subject_id="1" * 64),
    ]
    report = render_terms_report((ct,), records)
    line = report.lines[0]
    assert line.verdict_rows_n == 1
    assert line.units_in_range == 1
    assert line.coverage_discrepancy is False


# --- 8. sampled-mode sampling rate (chunk 4's sampler) -----------------------
# Acceptance addendum item 4: "sampled-mode sampling rate must appear in the
# report fold envelope (absent from terms_report.py:123-140)." This module
# never re-derives the rate (same discipline as the self-seeded-sampler
# caveat) -- it only has somewhere to render what chunk 4's sampler already
# decided, supplied per-epoch via ``epoch_sampling_rates``.


def test_sampled_mode_line_carries_the_supplied_sampling_rate():
    ct = _judged_term()
    c_digest = compiled_term_digest(ct)
    records = [_verdict_record(term_id=ct.term_id, c_digest=c_digest, epoch="epoch-a", verdict="pass")]
    report = render_terms_report((ct,), records, epoch_sampling_rates={"epoch-a": 0.1})
    line = report.lines[0]
    assert line.envelope.sampling_rate == 0.1


def test_unsampled_judged_line_does_not_fabricate_a_sampling_rate():
    ct = _judged_term()
    c_digest = compiled_term_digest(ct)
    records = [_verdict_record(term_id=ct.term_id, c_digest=c_digest, epoch="epoch-a", verdict="pass")]
    # no epoch_sampling_rates supplied at all -- e.g. a full-census epoch
    report = render_terms_report((ct,), records)
    line = report.lines[0]
    assert line.envelope.sampling_rate is None


def test_sampling_rate_is_scoped_per_epoch_never_bled_across_lines():
    ct = _judged_term()
    c_digest = compiled_term_digest(ct)
    records = [
        _verdict_record(term_id=ct.term_id, c_digest=c_digest, epoch="epoch-a", verdict="pass"),
        _verdict_record(term_id=ct.term_id, c_digest=c_digest, epoch="epoch-b", verdict="fail"),
    ]
    report = render_terms_report((ct,), records, epoch_sampling_rates={"epoch-a": 0.25})
    by_epoch = {line.epoch: line for line in report.lines}
    assert by_epoch["epoch-a"].envelope.sampling_rate == 0.25
    assert by_epoch["epoch-b"].envelope.sampling_rate is None


def test_envelope_to_dict_carries_the_sampling_rate():
    ct = _judged_term()
    c_digest = compiled_term_digest(ct)
    records = [_verdict_record(term_id=ct.term_id, c_digest=c_digest, epoch="epoch-a", verdict="pass")]
    report = render_terms_report((ct,), records, epoch_sampling_rates={"epoch-a": 0.5})
    assert report.lines[0].envelope.to_dict()["sampling_rate"] == 0.5
