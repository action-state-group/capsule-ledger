# SPDX-License-Identifier: Apache-2.0
"""The prepared ledger for ``[ldg-live-compile-demo]``: one real
tau2-bench airline trajectory, replayed offline through
``record-grounding-bench``'s ``rgb shift replay`` (``[ldg-tau2-replay-adapter]``)
-- no network, no API key, no model call, at either replay time or demo
time. This is the "batch run happens before the room" half of the split
(``[ldg-live-compile-demo]``'s inbox stanza, 2026-08-20).

Byte identity check (``expected_sha256`` below) pins the exact bytes
verified in ``[ldg-tau2-replay-adapter]``'s own DONE report -- two
independent replays under ``env -i`` with no network produced this same
digest. A change here means either the fixture was regenerated (expected
to still verify) or corrupted in transit (must not verify) -- this test
tells the two apart.
"""
from __future__ import annotations

from pathlib import Path

from capsule_ledger.cli.main import main as cli_main

FIXTURE = Path(__file__).parent.parent / "capsule_ledger/examples/live_compile_demo/fixtures/tau2_airline_task40_trial0.jsonl"


def test_fixture_is_the_verified_byte_identical_replay():
    import hashlib

    digest = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    assert digest == "234ddabbd5f40ec88fcf5ae89d20ac2b19d052bbc142acdbc8b20e679a46c96b"


def test_fixture_has_seventeen_capsules():
    lines = [line for line in FIXTURE.read_text().splitlines() if line.strip()]
    assert len(lines) == 17


def test_fixture_bundles_and_verifies_offline(tmp_path):
    bundle_path = tmp_path / "bundle.json"
    assert cli_main(["bundle", "--ledger", str(FIXTURE), "--out", str(bundle_path)]) == 0
    assert cli_main(["verify", "--bundle", str(bundle_path)]) == 0
