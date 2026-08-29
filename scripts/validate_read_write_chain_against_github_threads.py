#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Design §12 validation: run ``setup.observe``'s new "read" kind + dispatch
``read_ref`` chaining against a real cold-start corpus, offline.

Backward-judge design doc §14 names a second test corpus alongside tau2
airline: a small set of GitHub issue threads (a partner's cold-start +
read-capture cases), each carrying both sides of one agent action -- the
issue/comments/timeline it **read**, and a digest-locked investigation
comment it **wrote**. That corpus is a THIRD PARTY'S own issue-tracker
content (real usernames, real internal repo/host names) and is
**deliberately not vendored into this public repo** -- unlike tau2-bench's
already-public airline transcripts (see ``scripts/vendor_tau2_airline_*``),
there is no license to redistribute it. This script instead takes a
``--corpus-dir`` pointing at wherever that corpus lives locally, reads it,
and prints only digests and pass/fail -- never issue/comment content.

**What each case proves.** Per case file (schema ``github_issue_thread_
export/v1``): everything with a timestamp strictly before the investigation
comment's own ``created_at`` is "what the agent read" (the issue plus prior
comments/timeline -- the investigation comment itself is excluded, since the
agent had not written it yet); the investigation comment's body is "what the
agent wrote". This script:

1. Records the read as a ``setup.observe`` "read" event, digest = this
   repo's own ``agent_action_capsule.json_digest`` over the read snapshot
   (the same canonicalization the ledger seals with -- not a bespoke hash).
2. Records the write as a "dispatch" event, ``read_ref`` pointing at the
   read above, ``target_digest`` = plain ``sha256`` of the comment body --
   the same construction as each case's own ``locked_investigation_comment_
   sha256`` fixture field, so a mismatch here means either this script's
   read/write split disagrees with the fixture, or the fixture itself
   drifted.
3. Asserts the resulting write capsule's ``chain.parent_capsule_id`` is the
   read capsule -- the mechanism design §12 exists for: "the agent acted on
   what it actually read" is now a provable chain, not an unrecorded claim.

Run: ``python scripts/validate_read_write_chain_against_github_threads.py
--corpus-dir /path/to/github-threads``
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import tempfile
from pathlib import Path

from agent_action_capsule import json_digest

from capsule_ledger.guards.signing import LocalSigner
from capsule_ledger.ledger.store import LedgerStore
from capsule_ledger.setup.observe import EVENT_DISPATCH, EVENT_READ, ObserveRecorder

EXPECTED_SCHEMA = "github_issue_thread_export/v1"


def _read_snapshot(case: dict, *, before: str) -> dict:
    """Everything with a timestamp strictly before ``before`` (the
    investigation comment's own ``created_at``) -- the issue plus whatever
    comments/timeline items preceded the write. Field-level, never raw
    body-of-unrelated-comments-shaped -- included as-is because the point is
    "what the agent's context window held", not a redaction exercise."""
    comments = [c for c in case["comments"] if c["created_at"] < before]
    timeline = [t for t in case["timeline"] if t.get("created_at", before) < before]
    return {"issue": case["issue"], "comments": comments, "timeline": timeline}


def _validate_case(path: Path) -> tuple[str, bool, str]:
    case = json.loads(path.read_text())
    if case.get("schema_version") != EXPECTED_SCHEMA:
        return path.name, False, f"unexpected schema_version {case.get('schema_version')!r}"

    demo = case["demo_case"]
    investigation_comment_id = demo["investigation_comment_id"]
    locked_digest = demo["locked_investigation_comment_sha256"]

    comment = next((c for c in case["comments"] if c["id"] == investigation_comment_id), None)
    if comment is None:
        return path.name, False, "investigation_comment_id not found in comments"
    body_digest = hashlib.sha256(comment["body"].encode("utf-8")).hexdigest()
    if body_digest != locked_digest:
        return path.name, False, "investigation comment body no longer matches locked_investigation_comment_sha256"

    snapshot = _read_snapshot(case, before=comment["created_at"])
    read_digest = json_digest(snapshot)

    with tempfile.TemporaryDirectory() as tmp:
        ledger = LedgerStore(tmp)
        try:
            signer = LocalSigner(key_id="validate-read-write-chain", secret=b"validation-only")
            recorder = ObserveRecorder(
                ledger=ledger, signer=signer, operator="op", developer="dev", heartbeat_stream=io.StringIO()
            )
            summary = recorder.run(
                [
                    {"kind": "read", "read_id": "read", "read_digest": read_digest, "source": path.stem},
                    {
                        "kind": "dispatch",
                        "action_class": "investigation_comment",
                        "tool": "post_comment",
                        "target_digest": body_digest,
                        "read_ref": "read",
                    },
                ]
            )
            if summary.unmapped:
                return path.name, False, f"unmapped event(s): {[u.reason for u in summary.unmapped]}"
            records = list(ledger.scan())
        finally:
            ledger.close()
    read_capsule = next(r.capsule for r in records if (r.capsule.get("asg_payload") or {}).get("event") == EVENT_READ)
    write_capsule = next(
        r.capsule for r in records if (r.capsule.get("asg_payload") or {}).get("event") == EVENT_DISPATCH
    )
    chain = write_capsule.get("chain") or {}
    if chain.get("parent_capsule_id") != read_capsule["capsule_id"]:
        return path.name, False, "write capsule did not chain to the read capsule"
    return path.name, True, f"read_digest={read_digest} write_target_digest={body_digest}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--corpus-dir", required=True, type=Path, help="directory of *.json case files")
    args = parser.parse_args()

    cases = sorted(args.corpus_dir.glob("*.json"))
    if not cases:
        print(f"no *.json case files found under {args.corpus_dir}", file=sys.stderr)
        return 2

    failures = 0
    for path in cases:
        name, ok, detail = _validate_case(path)
        print(f"{'PASS' if ok else 'FAIL'} {name}: {detail}")
        if not ok:
            failures += 1

    print(f"\n{len(cases) - failures}/{len(cases)} case(s) passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
