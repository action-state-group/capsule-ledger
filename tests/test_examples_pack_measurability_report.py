# SPDX-License-Identifier: Apache-2.0
"""``examples.pack_measurability_report`` -- the runnable script wrapping
``packs.measurability_report``. $0, no network, no model calls -- a pure
local report, so unlike the Vertex live-run scripts this needs no mock
transport at all."""
from __future__ import annotations

import json
from pathlib import Path

from capsule_ledger.examples import pack_measurability_report as report_mod

STANDARD_VENDOR_DIR = Path(__file__).parent.parent / "capsule_ledger" / "packs" / "catalog" / "standard-vendor"


def _write_corpus(tmp_path: Path, units: list[dict]) -> Path:
    path = tmp_path / "units.jsonl"
    with open(path, "w", encoding="utf-8") as fh:
        for unit in units:
            fh.write(json.dumps(unit) + "\n")
    return path


def test_runs_end_to_end_against_the_real_standard_vendor_pack(tmp_path, capsys):
    corpus_path = _write_corpus(
        tmp_path,
        [
            {"messages": [{"role": "user", "content": "hi", "tool_call_names": []}]},
            {"messages": [{"role": "user", "content": "bye", "tool_call_names": []}]},
        ],
    )
    rc = report_mod.main(
        ["--pack-dir", str(STANDARD_VENDOR_DIR), "--corpus", str(corpus_path), "--entity-key", "session_id"]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "pack: asg/standard-vendor" in out
    assert "measurability report -- 22 outcome(s)" in out
    # neither unit carries a session_id -> both resolve to the SAME key
    # (None) -> repeat traffic present -> fold_counterparty rows fall
    # through to the instrument check rather than the not-enough-traffic line
    assert "can't be shown" not in out


def test_no_repeat_traffic_when_session_id_is_actually_distinct(tmp_path, capsys):
    corpus_path = _write_corpus(
        tmp_path,
        [
            {"session_id": "shift-101-1", "messages": [{"role": "user", "content": "hi"}]},
            {"session_id": "shift-101-2", "messages": [{"role": "user", "content": "bye"}]},
        ],
    )
    rc = report_mod.main(
        ["--pack-dir", str(STANDARD_VENDOR_DIR), "--corpus", str(corpus_path), "--entity-key", "session_id"]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "can't be shown -- not enough repeat traffic in this demo" in out


def test_entity_key_is_required_and_closed_choice(capsys):
    import pytest

    with pytest.raises(SystemExit):
        report_mod.main(["--pack-dir", str(STANDARD_VENDOR_DIR), "--corpus", "/dev/null"])  # missing --entity-key
