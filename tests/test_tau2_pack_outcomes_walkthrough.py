# SPDX-License-Identifier: Apache-2.0
"""``[demo/tau2-pack-outcomes-walkthrough]``: smoke-tests the walkthrough
end to end against the REAL demo-chunk-1 tau2-airline corpus fixture, same
skip-if-absent convention as ``test_airline_pack_desk.py`` -- an honest
integration test over a real fixture, not a hermetic unit test.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from capsule_ledger.examples.tau2_pack_outcomes_walkthrough import main

CORPUS_PATH = (
    Path(__file__).resolve().parents[3]
    / "record-grounding-bench"
    / "demo-chunk1-tau2-corpus"
    / "data"
    / "fixtures"
    / "tau2-airline-corpus-v1"
)
RGB_SRC = (
    Path(__file__).resolve().parents[3] / "record-grounding-bench" / "demo-chunk1-tau2-corpus" / "src"
)

pytestmark = pytest.mark.skipif(
    not CORPUS_PATH.is_dir() or not RGB_SRC.is_dir(),
    reason=(
        f"real demo-chunk-1 tau2-airline corpus fixture not found at {CORPUS_PATH} -- "
        "checkout record-grounding-bench's demo/chunk1-tau2-corpus worktree as a sibling "
        "of capsule-ledger's own _worktrees/ to run this integration test"
    ),
)


def test_walkthrough_runs_clean_and_prints_all_three_parts(capsys):
    rc = main(["--corpus", str(CORPUS_PATH), "--rgb-src", str(RGB_SRC)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "PART 1 -- THE DATASET" in out
    assert "PART 2 -- THE PACK OF OUTCOMES" in out
    assert "PART 3 -- DRILL DOWN" in out
    # the honest, mechanically-verified corpus stats (not tuned)
    assert "total capsule records     : 1757" in out
    assert "distinct subjects (conversation sessions) : 73" in out
    # the honest census-grading finding (also asserted by test_airline_pack_desk.py)
    assert "0 of 959 resolve" in out
    # census + sampling-rate + coverage-discrepancy, exercised for the one
    # judge-shaped term this walkthrough seals a sampled verdict fixture for
    assert "sampling_rate=0.25" in out
    assert "coverage_discrepancy=True" in out
    # refusal rows render, never dropped
    assert "subjective_state_unattestable" in out


def test_walkthrough_is_deterministic_modulo_timestamps(capsys):
    import re

    main(["--corpus", str(CORPUS_PATH), "--rgb-src", str(RGB_SRC)])
    first = capsys.readouterr().out
    main(["--corpus", str(CORPUS_PATH), "--rgb-src", str(RGB_SRC)])
    second = capsys.readouterr().out

    def _scrub(text: str) -> str:
        return re.sub(r"[0-9a-f]{16,64}", "<digest>", text)

    assert _scrub(first) == _scrub(second)
