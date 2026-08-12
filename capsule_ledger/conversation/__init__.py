# SPDX-License-Identifier: Apache-2.0
"""The interim conversation-capsule profile (pre-VAC).

[ldg-conversation-capsule-profile]: per-turn ``fyi`` capsules sealed AT TURN
TIME (speaker role, turn-content digest -- never the content itself),
chained turn-to-turn so there is no unsigned window between a turn
happening and the ledger holding a signed record of it, plus one
session-close capsule binding every turn's digest into a single session
digest (Merkle-style, via ``capsule_ledger.mmr``) for selective disclosure
at TURN granularity.

This is the interim, ledger-native shape -- it migrates to Verifiable
Agent Conversations (Birkholz et al., COSE_Sign1 session records) once that
cross-party coordination lands; the no-unsigned-window property this module
establishes is itself a candidate contribution back to that draft, which
today has no equivalent guarantee.

Per-speaker judgment targeting (B3, the judge harness) reads
``speaker_role`` off these turn capsules -- ``SPEAKER_ROLES`` is the
complete, closed vocabulary a judge may target.

Public surface:
- ``build_turn_capsule`` / ``build_session_close_capsule`` -- pure capsule
  builders (no ledger I/O), same layering as ``guards.capsule``.
- ``find_session_turns`` / ``find_session_close`` -- read a session back off
  any ``LedgerAPI``.
- ``session_root`` / ``turn_inclusion_proof`` / ``verify_turn_inclusion`` --
  the Merkle session-digest primitives (``.merkle``).
- ``ConversationSession`` -- the stateful recorder: seals and appends each
  turn immediately, then ``close()``s the session.
"""
from __future__ import annotations

from .capsules import (
    EVENT_CONVERSATION_TURN,
    EVENT_SESSION_CLOSE,
    SPEAKER_ROLES,
    InvalidSpeakerRole,
    build_session_close_capsule,
    build_turn_capsule,
    find_session_close,
    find_session_turns,
)
from .merkle import session_root, turn_inclusion_proof, verify_turn_inclusion
from .session import ConversationSession, SessionAlreadyClosedError

__all__ = [
    "SPEAKER_ROLES",
    "EVENT_CONVERSATION_TURN",
    "EVENT_SESSION_CLOSE",
    "InvalidSpeakerRole",
    "build_turn_capsule",
    "build_session_close_capsule",
    "find_session_turns",
    "find_session_close",
    "session_root",
    "turn_inclusion_proof",
    "verify_turn_inclusion",
    "ConversationSession",
    "SessionAlreadyClosedError",
]
