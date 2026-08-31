# SPDX-License-Identifier: Apache-2.0
"""``capsule setup propose --pack`` CLI wiring ([pack-propose-generic]): the
GENERIC measurability report, reachable from the real ``capsule`` CLI
("the git-like terminal interface"), not just a standalone script. Ties
together ``packs.measurability_report`` (already unit-tested in
``test_measurability_report.py``) with real CLI argument handling --
these tests are about the wiring, not re-proving the report logic itself.

READ-ONLY mode: no ``.capsule-setup/`` instance required, nothing
persisted -- confirmed by NOT calling ``capsule setup init`` first in any
of these tests, which would fail loudly if ``--pack`` mode accidentally
required an initialized instance.
"""
from __future__ import annotations

import json
from pathlib import Path

from capsule_ledger.cli.main import main

STANDARD_VENDOR_DIR = Path(__file__).parent.parent / "capsule_ledger" / "packs" / "catalog" / "standard-vendor"
AIRLINE_ENGAGEMENT_DIR = Path(__file__).parent.parent / "capsule_ledger" / "packs" / "catalog" / "airline-engagement"


def _write_corpus(tmp_path: Path, units: list[dict]) -> Path:
    path = tmp_path / "units.jsonl"
    with open(path, "w", encoding="utf-8") as fh:
        for unit in units:
            fh.write(json.dumps(unit) + "\n")
    return path


def test_pack_mode_runs_with_no_init_instance_and_persists_nothing(tmp_path, capsys):
    """No `capsule setup init` was run in this tmp_path at all -- --pack mode
    must not require one (distinct from every other setup verb)."""
    corpus_path = _write_corpus(tmp_path, [{"session_id": "s1", "messages": [{"role": "user", "content": "hi"}]}])
    rc = main(
        [
            "setup", "propose",
            "--project-dir", str(tmp_path),
            "--pack", str(STANDARD_VENDOR_DIR),
            "--corpus", str(corpus_path),
            "--entity-key", "session_id",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "pack: asg/standard-vendor" in out
    assert "READ-ONLY report -- no T1 declarations persisted" in out
    assert not (tmp_path / ".capsule-setup").exists()  # nothing written -- genuinely read-only


def test_pack_mode_without_corpus_errors_clearly(tmp_path, capsys):
    rc = main(["setup", "propose", "--project-dir", str(tmp_path), "--pack", str(STANDARD_VENDOR_DIR)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "--corpus is required" in err


def test_pack_mode_without_entity_key_errors_clearly_no_default(tmp_path, capsys):
    corpus_path = _write_corpus(tmp_path, [{"messages": []}])
    rc = main(
        ["setup", "propose", "--project-dir", str(tmp_path), "--pack", str(STANDARD_VENDOR_DIR), "--corpus", str(corpus_path)]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "--entity-key is required" in err


def test_pack_mode_against_the_real_vendored_corpus_shows_real_repeat_traffic(tmp_path, capsys):
    """The one real flat-JSONL corpus committed to this repo -- task_id
    genuinely repeats 4x (one per trial), so fold_counterparty/fold_cohort
    rows must fall through to the instrument check, not the
    not-enough-repeat-traffic line."""
    vendored = (
        Path(__file__).parent.parent
        / "capsule_ledger" / "examples" / "data" / "tau2_airline"
        / "tau2_conversations_claude-3-7-sonnet_airline_4trials.jsonl"
    )
    rc = main(
        [
            "setup", "propose",
            "--project-dir", str(tmp_path),
            "--pack", str(STANDARD_VENDOR_DIR),
            "--corpus", str(vendored),
            "--entity-key", "task_id",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "corpus:" in out and "200 unit(s)" in out
    assert "can't be shown" not in out  # real repeats present -- never hits the not-enough-traffic line here
    assert "C1" in out and "X1" in out


def test_pack_mode_works_on_the_airline_engagement_pack_too_not_only_standard_vendor(tmp_path, capsys):
    corpus_path = _write_corpus(tmp_path, [{"session_id": "s1", "messages": [{"role": "user", "content": "hi"}]}])
    rc = main(
        [
            "setup", "propose",
            "--project-dir", str(tmp_path),
            "--pack", str(AIRLINE_ENGAGEMENT_DIR),
            "--corpus", str(corpus_path),
            "--entity-key", "session_id",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "pack: airline-engagement" in out or "pack: asg/airline-engagement" in out


def test_pack_mode_errors_when_a_unit_is_missing_the_entity_key_field(tmp_path, capsys):
    """Review fix: a unit missing --entity-key's field must not silently
    collapse onto a fake shared key and pass the repeat-traffic gate."""
    corpus_path = _write_corpus(tmp_path, [{"messages": [{"role": "user", "content": "hi"}]}])  # no session_id
    rc = main(
        [
            "setup", "propose",
            "--project-dir", str(tmp_path),
            "--pack", str(STANDARD_VENDOR_DIR),
            "--corpus", str(corpus_path),
            "--entity-key", "session_id",
        ]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "missing the --entity-key field 'session_id'" in err


def test_default_propose_path_is_unaffected_when_pack_is_omitted(tmp_path, capsys, monkeypatch):
    """--pack is opt-in (default None) -- the pre-existing candidate-grading
    propose path must still require an initialized instance exactly as
    before, proving this change added a branch rather than restructuring
    the existing one."""
    rc = main(["setup", "propose", "--project-dir", str(tmp_path)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "no instance at" in err  # _require_initialized's own message, unchanged
