# SPDX-License-Identifier: Apache-2.0
"""``build_dry_run_report``/``replay`` thread a resolved manifest's digest
through to the real ``GuardEngine`` that produces every row's capsule."""
from __future__ import annotations

from pathlib import Path

from capsule_ledger.report import build_dry_run_report

FIXTURES = Path(__file__).parent / "fixtures"
NANDA = FIXTURES / "nanda_transaction_ledger.jsonl"


def test_report_manifest_digest_field_is_none_by_default(caps_fold):
    report = build_dry_run_report([str(NANDA)], caps_fold=caps_fold, since="7d")
    assert report.manifest_digest is None


def test_report_manifest_digest_is_populated_when_passed_through(caps_fold, resolved_manifest):
    report = build_dry_run_report(
        [str(NANDA)], caps_fold=caps_fold, since="7d", manifest_digest=resolved_manifest.manifest_digest
    )
    assert report.manifest_digest == resolved_manifest.manifest_digest

    # And it's not just a schema field: the underlying capsules the replay
    # actually produced carry it too.
    populated = [row.capsule for _, row in report.held_rows if "manifest_digest" in row.capsule.get("asg_payload", {})]
    assert populated, "expected at least one held row's capsule to cite the manifest digest"
    assert all(c["asg_payload"]["manifest_digest"] == resolved_manifest.manifest_digest for c in populated)
