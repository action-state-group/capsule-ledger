# SPDX-License-Identifier: Apache-2.0
"""``JudgeHarness``: the orchestration entry point tying a prompt (digest-
pinned), a ``Scorer`` (BYOM), and evidence together into a signed, appended
judgment capsule -- and the matching human spot-check adjudication call.

Mirrors ``conversation/session.py``'s ``ConversationSession`` shape:
``signer_provider`` is called once per record, never cached, so a signing
key that becomes unavailable mid-run fails that one call closed rather than
silently reusing a stale ``Signer`` or continuing unsigned (gating doc §1:
"an unsigned record is not a record").

This module never imports ``guards.engine`` and never gates anything --
"judge NEVER in the enforcement path" (B3) is enforced structurally by what
this module does and doesn't reach for, not just documented.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..guards.signing import Signer
from ..ledger.api import LedgerAPI
from ..ledger.records import LedgerRecord
from .capsules import build_adjudication_capsule, build_judgment_capsule
from .prompt import JudgePromptDefinition
from .scorer import JudgeEvidence, Scorer

__all__ = ["JudgeHarness"]


@dataclass
class JudgeHarness:
    ledger: LedgerAPI
    prompt: JudgePromptDefinition
    scorer: Scorer
    operator: str
    developer: str
    signer_provider: Callable[[], Signer]

    def run(
        self,
        *,
        evidence: JudgeEvidence,
        session_digest: str | None = None,
        chain_parent: str | None = None,
        timestamp: str | None = None,
        action_id: str | None = None,
    ) -> LedgerRecord:
        """Score ``evidence`` against ``self.prompt`` and append the
        resulting judgment capsule. The ``Scorer`` call happens first, so a
        scorer failure (bad dependency, model error) never produces a
        half-built or unsigned record."""
        result = self.scorer.score(evidence=evidence, prompt=self.prompt)
        capsule = build_judgment_capsule(
            prompt=self.prompt,
            evidence=evidence,
            result=result,
            operator=self.operator,
            developer=self.developer,
            signer=self.signer_provider(),
            session_digest=session_digest,
            chain_parent=chain_parent,
            timestamp=timestamp,
            action_id=action_id,
        )
        return self.ledger.append(capsule, consequential=False)

    def adjudicate(
        self,
        *,
        judgment: dict,
        label: str,
        agrees_with_judge: bool,
        rationale: str | None = None,
        timestamp: str | None = None,
        action_id: str | None = None,
    ) -> LedgerRecord:
        """Record a MANUAL spot-check adjudication of ``judgment`` (a sealed
        judgment capsule dict). See ``capsules.build_adjudication_capsule``
        for the honesty check on ``agrees_with_judge``/``label``."""
        capsule = build_adjudication_capsule(
            judgment=judgment,
            label=label,
            agrees_with_judge=agrees_with_judge,
            operator=self.operator,
            developer=self.developer,
            signer=self.signer_provider(),
            rationale=rationale,
            timestamp=timestamp,
            action_id=action_id,
        )
        return self.ledger.append(capsule, consequential=False)
