# SPDX-License-Identifier: Apache-2.0
"""``examples.live_compile_demo.demo`` -- the on-stage payload. Exercises
the exact sequence the presenter runs: compile, edit, recompile, and the
two drift-check calls (clean re-derive, caught mutant)."""
from __future__ import annotations

from capsule_ledger.examples.live_compile_demo import demo


def test_run_produces_a_clean_and_a_caught_drift_result(tmp_path):
    result = demo.run(tmp_path / "ledger")

    assert result.initial_compiled.forward.digest() != result.edited_compiled.forward.digest()
    assert result.initial_compiled.backward.digest() != result.edited_compiled.backward.digest()

    assert result.clean_drift.drifted is False
    assert result.caught_drift.drifted is True
    assert result.caught_drift.p_drifted is True
    assert result.caught_drift.f_drifted is True


def test_run_seals_two_chained_compilation_records(tmp_path):
    result = demo.run(tmp_path / "ledger")

    d2_detail = result.edited_capsule["asg_payload"]["detail"]
    d1_detail = result.initial_capsule["asg_payload"]["detail"]
    assert d2_detail["d_prev_digest"] == d1_detail["d_digest"]
    assert result.initial_capsule["capsule_id"] != result.edited_capsule["capsule_id"]


def test_main_writes_a_ledger_that_bundles_and_verifies_offline(tmp_path, capsys):
    from capsule_ledger.cli.main import main as cli_main

    out_dir = tmp_path / "out"
    exit_code = demo.main(["--out-dir", str(out_dir)])
    assert exit_code == 0
    assert (out_dir / "segments").exists()

    bundle_path = out_dir / "bundle.json"
    assert cli_main(["bundle", "--ledger", str(out_dir), "--out", str(bundle_path)]) == 0
    assert bundle_path.exists()
    assert cli_main(["verify", "--bundle", str(bundle_path)]) == 0
