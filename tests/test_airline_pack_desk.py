# SPDX-License-Identifier: Apache-2.0
"""``[ldg-t2r-tau2-demo]`` chunk 2 -- pack-through-desk, exercised against
the REAL demo-chunk-1 tau2-airline corpus fixture committed to
record-grounding-bench. This is the ASG-workspace sibling-repo layout's
canonical worktree location (``_worktrees/record-grounding-bench/
demo-chunk1-tau2-corpus``) -- skipped, not failed, when that worktree
is not present (a fresh clone of capsule-ledger alone, or CI without the
sibling repo checked out), so this test is honest about being an
integration test over a real fixture, not a hermetic unit test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from capsule_ledger.compiler.terms_desk import verify_terms_compilation_record
from capsule_ledger.examples.airline_engagement_pack import build_airline_engagement_pack
from capsule_ledger.examples.airline_pack_desk import (
    render_report,
    run_airline_pack_through_desk,
)
from capsule_ledger.ledger import LedgerStore

CORPUS_PATH = (
    Path(__file__).resolve().parents[3]
    / "record-grounding-bench"
    / "demo-chunk1-tau2-corpus"
    / "data"
    / "fixtures"
    / "tau2-airline-corpus-v1"
)

pytestmark = pytest.mark.skipif(
    not CORPUS_PATH.is_dir(),
    reason=(
        f"real demo-chunk-1 tau2-airline corpus fixture not found at {CORPUS_PATH} -- "
        "checkout record-grounding-bench's demo/chunk1-tau2-corpus worktree as a sibling "
        "of capsule-ledger's own _worktrees/ to run this integration test"
    ),
)


@pytest.fixture
def desk_ledger(tmp_path):
    ledger = LedgerStore(tmp_path / "desk-ledger")
    yield ledger
    ledger.close()


def test_all_nine_pack_rows_produce_report_lines(desk_ledger, tmp_path):
    result = run_airline_pack_through_desk(
        CORPUS_PATH,
        desk_ledger=desk_ledger,
        declarations_root=tmp_path / "declarations",
    )
    pack_rows = build_airline_engagement_pack().rows
    assert len(result.report_lines) == len(pack_rows) == 9


def test_refusal_row_is_preserved_on_the_report(desk_ledger, tmp_path):
    """A8 ("the customer was satisfied") REFUSES on both sides regardless
    of corpus -- design's pack rule: refusal rows render exactly as
    prominently as every other row, never dropped."""
    result = run_airline_pack_through_desk(
        CORPUS_PATH,
        desk_ledger=desk_ledger,
        declarations_root=tmp_path / "declarations",
    )
    a8 = next(line for line in result.report_lines if line.term_id == "term.airline_pack.a8")
    assert a8.is_refused
    assert a8.refusal_reason_code == "subjective_state_unattestable"
    assert a8.clause_ref == "airline-engagement-pack/A8"
    rendered = render_report(result)
    assert "term.airline_pack.a8" in rendered
    assert "REFUSED" in rendered or "refused" in rendered.lower()


def test_every_report_line_carries_clause_ref_and_c_digest(desk_ledger, tmp_path):
    """design §3/[rev4]: every line is walkable clause -> term -> compiled
    check (c_digest) -> number."""
    result = run_airline_pack_through_desk(
        CORPUS_PATH,
        desk_ledger=desk_ledger,
        declarations_root=tmp_path / "declarations",
    )
    for line in result.report_lines:
        assert line.clause_ref.startswith("airline-engagement-pack/A")
        assert line.c_digest == result.c_capsule["capsule_id"]


def test_census_grading_against_the_real_corpus_narrows_the_non_refused_rows(desk_ledger, tmp_path):
    """The honest finding this chunk surfaces (module docstring): the real
    fixture carries no offer/response-shaped capsules of any kind (it is a
    conversation-turn recording, digest-only by the H2 invariant), so
    every non-refused row's census grade legitimately downgrades to
    WITH-INSTRUMENTATION rather than reproducing
    airline_engagement_pack.py's offline-dataset numbers. This is the
    designed-for zero-coverage behavior of propose_from_ledger, not a bug
    in this module."""
    result = run_airline_pack_through_desk(
        CORPUS_PATH,
        desk_ledger=desk_ledger,
        declarations_root=tmp_path / "declarations",
    )
    non_refused = [line for line in result.report_lines if not line.is_refused]
    assert len(non_refused) == 8
    for line in non_refused:
        assert line.backward_verdict == "WITH-INSTRUMENTATION"
        assert line.missing_instrument is not None
        assert line.coverage_n == 0
        assert line.coverage_m == 0


def test_t1_sealed_compilation_record_verifies_clean(desk_ledger, tmp_path):
    """T1 confirmation SCRIPTED and SEALED: the sealed C recomputes clean
    against the confirmed terms document alone (verify_terms_compilation_record
    -- never merely checking the sealed record's own internal consistency)."""
    result = run_airline_pack_through_desk(
        CORPUS_PATH,
        desk_ledger=desk_ledger,
        declarations_root=tmp_path / "declarations",
    )
    drift = verify_terms_compilation_record(
        result.c_capsule["asg_payload"]["detail"], t_document=result.terms_document
    )
    assert not drift.drifted


def test_desk_run_does_not_mutate_the_source_corpus_fixture():
    """copied_corpus_ledger copies before opening -- LedgerStore.__init__
    opens index.sqlite3 in WAL mode, which would otherwise write -wal/-shm
    files into record-grounding-bench's own committed worktree."""
    before = {p.name for p in CORPUS_PATH.iterdir()}
    from capsule_ledger.examples.airline_pack_desk import copied_corpus_ledger
    from capsule_ledger.setup.candidates import DEFAULT_CANDIDATES
    from capsule_ledger.setup.propose import propose_from_ledger

    with copied_corpus_ledger(CORPUS_PATH) as ledger:
        propose_from_ledger(ledger, candidates=DEFAULT_CANDIDATES, allow_zero_coverage=True)
    after = {p.name for p in CORPUS_PATH.iterdir()}
    assert before == after
