# SPDX-License-Identifier: Apache-2.0
"""`capsule fold` CLI stub: hot-load catalog, lint, and replay-over-a-ledger.

``tests/fixtures/sample_ledger.jsonl`` is a checked-in copy of
capsule-emit/examples/amaury-receipt-pack/sample_ledger.jsonl (the fixture
named in the T1 acceptance criteria), copied in so CI — which only checks out
this repo — can run the replay without a sibling checkout.
"""
from __future__ import annotations

import json
from pathlib import Path

from capsule_ledger.cli.main import main

FIXTURE_LEDGER = Path(__file__).parent / "fixtures" / "sample_ledger.jsonl"


def test_fold_list_builtin_catalog(capsys):
    assert main(["fold", "list"]) == 0
    out = capsys.readouterr().out
    assert "actions.executed_count/1.0.0" in out


def test_fold_lint_ok(capsys):
    path = Path(__file__).parent.parent / "capsule_ledger" / "folds" / "catalog_defs" / "actions.executed_count.yaml"
    assert main(["fold", "lint", str(path)]) == 0
    out = capsys.readouterr().out
    assert "actions.executed_count/1.0.0" in out


def test_fold_lint_bad_definition(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("fold_id: not-a-namespaced-id\nreads: []\nreduce: {reducer: count}\nemit: count\n")
    assert main(["fold", "lint", str(bad)]) == 1
    err = capsys.readouterr().err
    assert "invalid_fold_id_namespace" in err


def test_fold_test_replays_sample_ledger_and_prints_envelope(capsys):
    rc = main(
        [
            "fold",
            "test",
            "actions.executed_count/1.0.0",
            "--ledger",
            str(FIXTURE_LEDGER),
            "--key",
            "procurement-agent@v1",
        ]
    )
    assert rc == 0
    envelope = json.loads(capsys.readouterr().out)
    assert set(envelope.keys()) == {"fold", "range", "tree_size", "checkpoint", "result", "evaluated_at", "staleness"}
    assert envelope["range"] == [0, 3]
    assert envelope["tree_size"] == 4
    # 2 of the 4 sample records reach disposition.verdict_class == "executed".
    assert envelope["result"] == 2


def test_fold_new_writes_template(tmp_path):
    rc = main(["fold", "new", "demo.thing/1.0.0", "--dir", str(tmp_path)])
    assert rc == 0
    out_path = tmp_path / "demo.thing.yaml"
    assert out_path.exists()
    assert "fold_id: demo.thing/1.0.0" in out_path.read_text()
