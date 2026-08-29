# SPDX-License-Identifier: Apache-2.0
"""Design §11/§14's second corpus: the Alchemy GitHub-threads cold-start
cases (5 real IBM ``lakehouse/tracker`` issues, issue+comments+timeline the
agent read plus a digest-locked investigation comment it wrote) exercise
the read-missing path. **These cases never went through capsule-emit at
all** -- they are raw GitHub API exports, design-time-only fixtures (§14:
"used design-time only ... never cited as sealed evidence"), so a term
requiring "the agent's read became a capsule" is, honestly, unprovable
against them today: the read/poll emit side (``[ldg-bj-emit-read-side-
python]``) hasn't landed yet. That is exactly the case this module proves:
read-missing -> insufficient_evidence, naming the field, never a fail.

Same skip-if-absent convention as ``test_tau2_pack_outcomes_walkthrough.py``
-- the corpus lives outside this repo (workspace-level ``_work/alchemy/``,
not committed here), so this integration test only runs where that sibling
data happens to be checked out; it is not part of the public repo's own
committed fixtures.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from capsule_ledger.compiler.session_rollup import rollup_unprovable_sessions
from capsule_ledger.guards import LocalSigner
from capsule_ledger.guards.capsule import build_event_capsule
from capsule_ledger.judge.evidence_completeness import EvidenceRequirement, resolve_verdict, verdict_detail


def _find_alchemy_corpus(start: Path) -> Path | None:
    for parent in start.parents:
        candidate = parent / "_work" / "alchemy" / "github-threads-sample" / "github-threads"
        if candidate.is_dir():
            return candidate
    return None


CORPUS_DIR = _find_alchemy_corpus(Path(__file__).resolve())

pytestmark = pytest.mark.skipif(
    CORPUS_DIR is None,
    reason=(
        "Alchemy github-threads-sample corpus not found under any ancestor's _work/alchemy/ -- "
        "see design doc §14 for how to obtain it; this integration test is skip-if-absent, same "
        "convention as test_tau2_pack_outcomes_walkthrough.py"
    ),
)

OPERATOR = "alchemy-read-missing-demo"
DEVELOPER = "alchemy-read-missing-demo@v1"
TERM_ID = "term.grounded_in_what_was_read"
_signer = LocalSigner(key_id="alchemy-demo-key", secret=b"alchemy-demo-secret")

# The evidence a "the write is grounded in what the agent read" term needs
# (design §12): a read-observation capsule the write's chain_parent points
# back at. Provisional field name pending [ldg-bj-emit-read-side-python]'s
# actual wire shape -- what matters here is that it is absent from these
# raw-GitHub-export fixtures today, honestly, not what it will eventually
# be called.
_READ_CHAIN_REQUIREMENT = EvidenceRequirement(
    path="read_observation.chain_parent_digest",
    label="read_observation.chain_parent_digest (the agent's read of the issue+comments+timeline was never sealed as a capsule)",
)


def _load_cases() -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(CORPUS_DIR.glob("case-*.json"))]


def test_corpus_has_the_expected_five_cases():
    cases = _load_cases()
    assert len(cases) == 5
    assert {c["demo_case"]["case_id"] for c in cases} == {"case-a", "case-b", "case-c", "case-d", "case-e"}


def _judge_must_not_run(case_id: str):
    def judge() -> str:  # pragma: no cover - must never be invoked
        raise AssertionError(f"judge invoked for {case_id} despite missing read evidence")

    return judge


def test_every_case_is_insufficient_evidence_never_pass_or_fail_and_the_judge_never_runs():
    cases = _load_cases()
    for case in cases:
        case_id = case["demo_case"]["case_id"]
        verdict, missing_evidence = resolve_verdict((_READ_CHAIN_REQUIREMENT,), case, judge=_judge_must_not_run(case_id))
        assert verdict == "insufficient_evidence"
        assert missing_evidence == _READ_CHAIN_REQUIREMENT.display_label


def test_the_report_names_the_missing_field_for_every_case():
    cases = _load_cases()
    records = []
    for case in cases:
        case_id = case["demo_case"]["case_id"]
        verdict, missing_evidence = resolve_verdict((_READ_CHAIN_REQUIREMENT,), case, judge=lambda: "pass")
        detail = verdict_detail(
            subject={"case_id": case_id},
            term_id=TERM_ID,
            c_digest="c" * 64,
            epoch="epoch-alchemy-demo",
            applicable=True,
            verdict=verdict,
            missing_evidence=missing_evidence,
        )
        assert detail["missing_evidence"] == _READ_CHAIN_REQUIREMENT.display_label
        records.append(build_event_capsule(operator=OPERATOR, developer=DEVELOPER, signer=_signer, event="judge_agent_verdict", detail=detail))

    rows = rollup_unprovable_sessions(records)
    assert len(rows) == 5
    for row in rows:
        assert row.status == "unprovable"
        assert row.failed_terms == ()
        assert len(row.unprovable_terms) == 1
        assert row.unprovable_terms[0].missing_evidence == _READ_CHAIN_REQUIREMENT.display_label
    # never laundered to a near-miss / fail list
    assert all(row.status != "near_miss" for row in rows)
