# SPDX-License-Identifier: Apache-2.0
"""``[ldg-bp-standard-vendor-pack]``: the standard-vendor pack.yaml, over the
GENERAL capsule vocabulary (design: action-state-ops/_work/backward-judge-
buildout/standard-outcome-pack-design.md §2/§4/§6) -- deliberately NOT
airline voice, so ONE pack should grade sensibly against corpora with two
very different shapes without ever crashing (design §6's generality proof
table).

**The two corpora, same as the rest of this wave's tests:**
- the real, committed tau2-bench airline conversation file
  (``examples/airline_engagement_pack.py``'s own vendored fixture,
  ``{"messages": [{"role", "content", "tool_call_names"}]}``-shaped).
- the Alchemy GitHub-threads-sample cold-start corpus (5 raw GitHub API
  issue+comments+timeline exports, no "messages" key at all) -- same
  skip-if-absent convention as ``test_alchemy_read_missing_insufficient_
  evidence.py``: lives outside this repo (workspace-level ``_work/alchemy/``),
  so this integration test only runs where that sibling data happens to be
  checked out.

**The mechanism reused verbatim, not reinvented:**
``capsule_ledger.packs.corpus_verify.verify_declared_not_measured`` is the
existing oracle that grades a pack's ``declared_not_measured`` claims
against a real corpus -- proving each WITH-INSTRUMENTATION row's "this
corpus doesn't carry the record this term needs" claim rather than trusting
it, and raising (not crashing silently) the moment one *does* resolve. This
module's own ``_coverage_map`` is a thin, static summary over the pack's own
declared ``measurability``/verdict fields (design §1's "propose returns a
coverage map: per outcome, N-of-M held, or WITH-INSTRUMENTATION naming the
field") -- it does not invent a second grading engine.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from capsule_ledger.examples.airline_engagement_pack import load_conversations
from capsule_ledger.packs.corpus_verify import verify_declared_not_measured
from capsule_ledger.packs.errors import CorpusVerificationError
from capsule_ledger.packs.loader import load_pack_dir
from capsule_ledger.packs.schema import PackDefinition

PACK_DIR = Path(__file__).parent.parent / "capsule_ledger" / "packs" / "catalog" / "standard-vendor"

_EXPECTED_IDS = {
    "S1", "S2", "S3", "S4",
    "V1", "V2",
    "J1", "J2", "J3", "J4", "J5", "J6",
    "F1",
    "C1", "C2", "C3", "C4", "C5", "C6",
    "T1", "T2",
    "X1",
}


def _find_alchemy_corpus(start: Path) -> Path | None:
    for parent in start.parents:
        candidate = parent / "_work" / "alchemy" / "github-threads-sample" / "github-threads"
        if candidate.is_dir():
            return candidate
    return None


ALCHEMY_CORPUS_DIR = _find_alchemy_corpus(Path(__file__).resolve())


def _load_alchemy_cases() -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(ALCHEMY_CORPUS_DIR.glob("case-*.json"))]


def _tau2_corpus() -> list[dict]:
    return load_conversations()


# --- basic shape ------------------------------------------------------


def test_the_pack_loads_clean_with_every_designed_row_and_no_airline_vocabulary():
    pack = load_pack_dir(PACK_DIR)
    by_id = {o.id: o for o in pack.outcomes}
    assert set(by_id) == _EXPECTED_IDS
    for outcome in pack.outcomes:
        for banned in ("airline", "customer", "flight", "fare", "seat"):
            assert banned not in outcome.statement.lower(), f"{outcome.id} leaks domain vocabulary: {outcome.statement!r}"


def test_the_integrity_core_is_must_have_and_topology_invariant_by_construction():
    """Design §6b: S1-S4/V1/F1 are the topology-invariant trust floor --
    every one of them must_have, none of them fold_counterparty/fold_agent/
    fold_cohort (those families are topology-dependent by definition)."""
    pack = load_pack_dir(PACK_DIR)
    by_id = {o.id: o for o in pack.outcomes}
    for oid in ("S1", "S2", "S3", "S4", "V1", "F1"):
        assert by_id[oid].tier == "must_have", oid
        assert by_id[oid].mode not in ("fold_counterparty", "fold_agent", "fold_cohort"), oid


def test_every_seven_mode_is_represented():
    pack = load_pack_dir(PACK_DIR)
    modes = {o.mode for o in pack.outcomes}
    assert modes == {
        "structural", "value", "judged", "fold_rollup", "fold_counterparty", "fold_agent", "fold_cohort",
    }


# --- the coverage map (design §1: "propose ... returns a coverage map") ---


def _coverage_map(pack: PackDefinition) -> dict[str, str]:
    """Per outcome: 'refused' (compiled REFUSED at authoring time, needs no
    corpus), 'held' (measurability == measured -- this pack claims it is
    checkable on any corpus that carries sealed free text or the field its
    evidence_rule names), or 'with_instrumentation' (declared_not_measured,
    naming the missing evidence_instrument) -- exactly the three states
    ``propose``'s own status glyphs (setup/propose.py's ``status_glyph``)
    render for a real ledger."""
    out: dict[str, str] = {}
    for o in pack.outcomes:
        if "REFUSED" in (o.forward_verdict, o.backward_verdict):
            out[o.id] = "refused"
        elif o.measurability == "declared_not_measured":
            out[o.id] = "with_instrumentation"
        else:
            out[o.id] = "held"
    return out


def _assert_sensible_coverage_map(coverage: dict[str, str]) -> None:
    assert set(coverage) == _EXPECTED_IDS
    assert set(coverage.values()) <= {"held", "with_instrumentation", "refused"}
    # design §1: a vendor doesn't satisfy every row -- some held, some
    # WITH-INSTRUMENTATION, never a bare pass-or-crash.
    assert any(v == "held" for v in coverage.values())
    assert any(v == "with_instrumentation" for v in coverage.values())
    assert coverage["S4"] == "refused"
    # the judged conduct family (free text only, both corpora carry it) is
    # always held -- it is the fold families needing typed trend fields
    # neither corpus emits yet that come back WITH-INSTRUMENTATION.
    for oid in ("J1", "J2", "J3", "J4", "J5", "J6"):
        assert coverage[oid] == "held"
    for oid in ("C1", "C2", "C3", "C4", "C5", "C6", "T1", "T2", "X1"):
        assert coverage[oid] == "with_instrumentation"


def test_the_coverage_map_is_sensible_and_identical_regardless_of_which_corpus_grades_it():
    """The coverage map is a static property of the pack's own declarations
    (design §1) -- grading it against either corpus must never crash, and
    must never silently change which rows are held vs WITH-INSTRUMENTATION
    (that would mean the pack's claims are corpus-dependent, which is
    exactly what 'declared_not_measured' must NOT be)."""
    pack = load_pack_dir(PACK_DIR)
    coverage = _coverage_map(pack)
    _assert_sensible_coverage_map(coverage)


# --- grading against the tau2 corpus (real, committed) --------------------


def test_grades_clean_against_the_real_committed_tau2_corpus_never_a_crash():
    pack = load_pack_dir(PACK_DIR)
    corpus = _tau2_corpus()
    assert corpus  # the real vendored file, not an empty stand-in
    verify_declared_not_measured(pack, corpus)  # must not raise
    _assert_sensible_coverage_map(_coverage_map(pack))


def test_raises_if_the_tau2_corpus_started_emitting_one_of_the_declared_instruments():
    """RED proof (QUEUE_PROTOCOL §7: a refusal test that never rejected
    anything proves nothing) -- mutate one real tau2 unit to carry a
    declared-missing field and confirm the oracle actually discriminates,
    the same RED/GREEN pair test_corpus_verify.py runs for the airline
    pack."""
    pack = load_pack_dir(PACK_DIR)
    corpus = _tau2_corpus()
    mutated = list(corpus)
    mutated[0] = dict(mutated[0])
    mutated[0]["messages"] = list(mutated[0]["messages"]) + [
        {"role": "assistant", "content": "n/a", "tool_call_names": [], "citation_digest": "deadbeef"}
    ]
    with pytest.raises(CorpusVerificationError) as exc:
        verify_declared_not_measured(pack, mutated)
    assert "S3" in str(exc.value)


# --- grading against the Alchemy github-threads corpus (skip-if-absent) ---

pytestmark_alchemy = pytest.mark.skipif(
    ALCHEMY_CORPUS_DIR is None,
    reason=(
        "Alchemy github-threads-sample corpus not found under any ancestor's _work/alchemy/ -- "
        "see design doc §14 for how to obtain it; this integration test is skip-if-absent, same "
        "convention as test_alchemy_read_missing_insufficient_evidence.py"
    ),
)


@pytestmark_alchemy
def test_grades_clean_against_the_alchemy_github_threads_corpus_never_a_crash():
    """Design §6's generality proof, literally exercised: the SAME pack
    (unmodified) grades against a corpus shaped nothing like tau2's
    ``{"messages": [...]}`` -- raw GitHub issue/comment/timeline exports,
    no 'messages' key at all -- and must neither crash nor silently change
    what it claims is held vs WITH-INSTRUMENTATION."""
    pack = load_pack_dir(PACK_DIR)
    corpus = _load_alchemy_cases()
    assert len(corpus) == 5
    verify_declared_not_measured(pack, corpus)  # must not raise, must not crash on the unfamiliar shape
    _assert_sensible_coverage_map(_coverage_map(pack))


@pytestmark_alchemy
def test_raises_if_the_alchemy_corpus_carried_one_of_the_declared_instruments_under_messages():
    """Same RED proof as the tau2 case, run against the Alchemy shape: even
    though these cases have no native 'messages' key, corpus_verify reads
    whatever 'messages' a unit carries -- proving the oracle would still
    catch a future Alchemy emitter revision that started producing one of
    this pack's declared-missing fields."""
    pack = load_pack_dir(PACK_DIR)
    corpus = _load_alchemy_cases()
    mutated = list(corpus)
    mutated[0] = dict(mutated[0])
    mutated[0]["messages"] = [
        {"role": "agent", "content": "n/a", "tool_call_names": [], "declared_authority_scope": "read_only"}
    ]
    with pytest.raises(CorpusVerificationError) as exc:
        verify_declared_not_measured(pack, mutated)
    assert "S2" in str(exc.value)
