# SPDX-License-Identifier: Apache-2.0
"""`capsule show` resolving a referenced capsule back to the conversation
turn that prompted it (``build_turn_reference_capsule`` / ``find_turn_reference``)."""
from __future__ import annotations

import hashlib

from capsule_ledger.cli.main import main
from capsule_ledger.conversation import ConversationSession, build_turn_reference_capsule
from capsule_ledger.guards import LocalSigner
from capsule_ledger.ledger import LedgerStore

OPERATOR = "acme-support"
DEVELOPER = "workforce-assistant@v1"


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_show_resolves_a_real_appended_capsule_to_its_turn(tmp_path, capsys):
    signer = LocalSigner(key_id="test-key-1", secret=b"test-secret")
    store = LedgerStore(tmp_path)
    try:
        session = ConversationSession(
            ledger=store, session_id="sess-1", operator=OPERATOR, developer=DEVELOPER, signer_provider=lambda: signer
        )
        turn = session.record_turn(speaker_role="assistant", content_digest=_digest("book it"))
        session.close()

        # A second, independently-appended turn stands in for a tool-call
        # capsule some other pipeline recorded on the same ledger.
        other_session = ConversationSession(
            ledger=store, session_id="sess-2", operator=OPERATOR, developer=DEVELOPER, signer_provider=lambda: signer
        )
        tool_stand_in = other_session.record_turn(speaker_role="user", content_digest=_digest("tool result"))
        other_session.close()

        reference = build_turn_reference_capsule(
            turn_capsule_id=turn.capsule_id,
            referenced_capsule_ids=[tool_stand_in.capsule_id],
            operator=OPERATOR,
            developer=DEVELOPER,
            signer=signer,
        )
        store.append(reference, consequential=False)

        rc = main(["show", tool_stand_in.capsule_id, "--ledger", str(tmp_path)])
        out = capsys.readouterr().out
    finally:
        store.close()

    assert rc == 0
    assert f"Turn:       {turn.capsule_id} (via {reference['capsule_id']})" in out


def test_show_omits_turn_line_when_capsule_is_unreferenced(tmp_path, capsys):
    signer = LocalSigner(key_id="test-key-1", secret=b"test-secret")
    store = LedgerStore(tmp_path)
    try:
        session = ConversationSession(
            ledger=store, session_id="sess-1", operator=OPERATOR, developer=DEVELOPER, signer_provider=lambda: signer
        )
        turn = session.record_turn(speaker_role="user", content_digest=_digest("hello"))
        rc = main(["show", turn.capsule_id, "--ledger", str(tmp_path)])
        out = capsys.readouterr().out
    finally:
        store.close()

    assert rc == 0
    assert "Turn:" not in out
