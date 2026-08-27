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
    # the honest finding: a direct resolve() fails (wrong digest scheme), but
    # this module's brute-force sha256 workaround recovers every turn's text
    assert "0 of 959 resolve via a direct PayloadStore.resolve" in out
    assert "959 of 959 resolve -- the turn text IS sealed" in out
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
        # 6, not 16: PART 3's drill-down also prints 8-char capsule-id
        # fingerprints (report/model.py's own truncation convention) for
        # demo-emitted capsules (e.g. the A8 refusal capsule) whose
        # underlying capsule_id embeds a real wall-clock timestamp -- the
        # corpus's OWN capsule ids/checkpoint roots are stable across runs
        # (loaded from disk), so this only ever launders timestamp-derived
        # digests, never a genuine content difference.
        return re.sub(r"[0-9a-f]{6,64}", "<digest>", text)

    assert _scrub(first) == _scrub(second)


def test_ascii_format_reports_the_same_numbers_as_verbose(capsys):
    main(["--corpus", str(CORPUS_PATH), "--rgb-src", str(RGB_SRC)])
    verbose_out = capsys.readouterr().out

    rc = main(["--corpus", str(CORPUS_PATH), "--rgb-src", str(RGB_SRC), "--format", "ascii"])
    assert rc == 0
    ascii_out = capsys.readouterr().out

    # no PART 1/2/3 narration banners in ascii mode
    assert "PART 1 -- THE DATASET" not in ascii_out
    assert "PART 2 -- THE PACK OF OUTCOMES" not in ascii_out
    assert "PART 3 -- DRILL DOWN" not in ascii_out
    # condensed sections present instead
    assert "## term outcomes (real, sealed corpus -- digest-verified turns)" in ascii_out
    assert "## drill-down: term -> case -> chain" in ascii_out
    assert "subjective_state_unattestable" in ascii_out

    # the real, digest-verified corpus terms are numerically identical between formats
    # (verbose indents these one level deeper under "2d. NEW: ...")
    for term_line in ("A1: 23 of 73", "A3b: 73 of 73", "A6: 47 of 73", "A7: 4 of 73"):
        assert f"- {term_line}" in ascii_out
        assert f"- {term_line}" in verbose_out


def test_permalink_out_builds_a_verifiable_bundle_and_offline_viewer(tmp_path, capsys):
    out_path = tmp_path / "permalink.json"
    rc = main(
        [
            "--corpus", str(CORPUS_PATH),
            "--rgb-src", str(RGB_SRC),
            "--format", "ascii",
            "--permalink-out", str(out_path),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "permalink: " in out
    assert "all verify" in out
    assert "verify: https://verify.agentactioncapsule.org/bundle#" in out

    assert out_path.is_file()
    viewer_path = out_path.with_suffix(".html")
    assert viewer_path.is_file()

    import json

    bundle = json.loads(out_path.read_text(encoding="utf-8"))
    assert bundle["bundle_version"] == "1"
    assert len(bundle["records"]) > 0
    assert all(v["ok"] for v in bundle["verification"].values())
    assert bundle["completeness_certificate"] is not None

    html = viewer_path.read_text(encoding="utf-8")
    # the one embed slot render_offline_viewer_html substitutes (see its own
    # docstring: "@@BUNDLE_FRAGMENT@@" legitimately reappears elsewhere in the
    # vendored template as BUNDLE_JS's own placeholder-detection logic, so
    # checking for the ABSENCE of the literal token would be a false negative)
    assert '<script>window.__BUNDLE_FRAGMENT_B64U__="@@BUNDLE_FRAGMENT@@";</script>' not in html
    assert "window.__BUNDLE_FRAGMENT_B64U__=" in html
