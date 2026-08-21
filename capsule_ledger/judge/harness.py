# SPDX-License-Identifier: Apache-2.0
"""``JudgeHarness``: the orchestration entry point tying a prompt (digest-
pinned), a ``Scorer`` (BYOM), and evidence together into a signed, appended
judgment capsule -- the matching human spot-check adjudication call, and the
judge drift check (design §6c item 2: re-run the same pinned judge over the
evidence it already cited, seal match-or-delta).

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
from .calibration import compute_judge_calibration_stats
from .capsules import (
    ExternalProofRef,
    build_adjudication_capsule,
    build_judge_drift_check_capsule,
    build_judgment_capsule,
    judge_pin_digest,
)
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
    # The harness's own declared policy: what fraction of judgments get a
    # human spot-check. Purely declarative here -- this module does not
    # enforce or act on it, it only pins it onto every judgment it produces
    # (the sampling decision itself is the caller's/CLI's, same "harness
    # pins, never decides" separation everywhere else in this module).
    adjudication_sampling_rate: float | None = None

    def run(
        self,
        *,
        evidence: JudgeEvidence,
        session_digest: str | None = None,
        chain_parent: str | None = None,
        timestamp: str | None = None,
        action_id: str | None = None,
        external_proof: ExternalProofRef | None = None,
    ) -> LedgerRecord:
        """Score ``evidence`` against ``self.prompt`` and append the
        resulting judgment capsule. The ``Scorer`` call happens first, so a
        scorer failure (bad dependency, model error) never produces a
        half-built or unsigned record.

        ``measured_agreement_rate`` is computed automatically from the
        ledger's own adjudication history for this exact judge pin (see
        ``calibration.compute_judge_calibration_stats``) -- ``None`` when
        this pin has no adjudicated judgments yet, never a fabricated 0%.
        """
        result = self.scorer.score(evidence=evidence, prompt=self.prompt)
        pin_digest = judge_pin_digest(
            model_id=result.model_id,
            model_version=result.model_version,
            sampling_params=result.sampling_params,
            prompt_digest=self.prompt.prompt_digest(),
        )
        measured_agreement_rate = compute_judge_calibration_stats(self.ledger, pin_digest).agreement_rate
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
            adjudication_sampling_rate=self.adjudication_sampling_rate,
            measured_agreement_rate=measured_agreement_rate,
            external_proof=external_proof,
        )
        return self.ledger.append(capsule, consequential=False)

    def check_drift(
        self,
        *,
        judgment: dict,
        evidence: JudgeEvidence,
        timestamp: str | None = None,
        action_id: str | None = None,
    ) -> LedgerRecord:
        """Re-run ``self.scorer``/``self.prompt`` over ``evidence`` -- the
        SAME evidence range ``judgment`` already cited -- and seal a
        ``judge_drift_check`` capsule chained to it. Always seals a record,
        whether the re-run matches or drifts (``build_judge_drift_check_capsule``
        raises ``JUDGE_PIN_MISSING`` if ``judgment`` predates the full pin)."""
        rerun_result = self.scorer.score(evidence=evidence, prompt=self.prompt)
        capsule = build_judge_drift_check_capsule(
            judgment=judgment,
            rerun_prompt=self.prompt,
            rerun_result=rerun_result,
            operator=self.operator,
            developer=self.developer,
            signer=self.signer_provider(),
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
