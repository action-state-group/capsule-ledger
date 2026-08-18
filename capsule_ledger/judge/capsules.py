# SPDX-License-Identifier: Apache-2.0
"""Builders for the judge harness's three record types: ``judge_judgment``
(one per judge run, the model-assisted recorded claim), ``judge_adjudication``
(a human-disposed spot-check chained to the judgment it disposes of), and
``judge_prompt_activated`` (a judge prompt/label-set change, capsuled the same
way a policy-manifest activation is -- ``policy/activation.py``).

Every builder here answers the B3 task's own framing: "who judged the judge,
with what prompt, on what evidence" must be answerable from the ledger alone.
A judgment capsule carries the model id, the prompt's own digest (never the
prompt text -- that lives in the pack/catalog the digest cites), and the
evidence RANGE (session id + evidence-ranged turn capsule ids, + the session
digest once the session has closed) -- never the evidence content itself
(H2 invariant, same as ``conversation/capsules.py``).

Judgment capsules are passive ``fyi`` records built via ``guards.capsule``'s
``build_event_capsule`` (same mechanism every other administrative record in
this codebase uses) -- a judgment is never a gate decision, and this module
never imports ``guards.engine``: the judge is structurally kept out of the
enforcement path, not just documented out of it (B3: "judge NEVER in the
enforcement path").

Adjudication capsules DO carry a real ``disposition`` block (unlike
``build_event_capsule``'s bare event records) -- "adjudications = human-
disposed capsules chained to judgments" is literally
``Disposition.human_disposed=True``, so this module builds one directly
rather than routing through ``build_event_capsule``, which never sets one.
"""
from __future__ import annotations

from agent_action_capsule import (
    AssuranceBlock,
    Capsule,
    Chain,
    Disposition,
    compute_capsule_id,
    json_digest,
)

from ..conversation.capsules import SPEAKER_ROLES
from ..guards.action import Action
from ..guards.capsule import build_event_capsule
from ..guards.signing import Signer
from ..ledger.api import LedgerAPI, ScanQuery
from ..ledger.records import LedgerRecord
from ..policy.activation import GENESIS_PARENT
from .errors import (
    ADJUDICATION_LABEL_MISMATCH,
    CONFIDENCE_OUT_OF_RANGE,
    EMPTY_EVIDENCE_RANGE,
    INVALID_SPEAKER_ROLE_TARGET,
    JUDGMENT_NOT_FOUND,
    LABEL_NOT_IN_LABEL_SET,
    JudgeError,
)
from .prompt import JudgePromptDefinition
from .scorer import JudgeEvidence, ScoreResult

__all__ = [
    "EVENT_JUDGMENT",
    "EVENT_ADJUDICATION",
    "EVENT_PROMPT_ACTIVATED",
    "build_judgment_capsule",
    "build_adjudication_capsule",
    "build_judge_prompt_activation_capsule",
    "find_judgments_for_session",
    "find_adjudications_for_judgment",
    "find_latest_prompt_activation",
]

EVENT_JUDGMENT = "judge_judgment"
EVENT_ADJUDICATION = "judge_adjudication"
EVENT_PROMPT_ACTIVATED = "judge_prompt_activated"

_SPEC_VERSION = "draft-mih-scitt-agent-action-capsule-02"
_FORMAT_VERSION = "2"

# The only registered chain.relation this module uses: "confirms" -- the
# adjudication (or judgment, when chained to a session) observes/records the
# outcome of its parent without closing any open state (registry §6: "this
# capsule observes or records the outcome of the parent -- the parent's open
# state remains"). A judgment/adjudication never resolves or supersedes
# anything; the record it comments on stays exactly as it was sealed.
CONFIRMS = "confirms"


def _rationale_digest(rationale: str | None) -> str | None:
    # Mirrors guards/capsule.py's ConstraintOutcome.evidence -> evidence_digest
    # pattern: free-text rationale is digested, never placed raw on a capsule.
    return json_digest({"rationale": rationale}) if rationale is not None else None


def _confidence_micros(confidence: float) -> int:
    # A raw float confidence is not digest-safe (agent_action_capsule's JCS
    # canonicalization MUST-FAILs any float in a digest-bearing field, same
    # rule folds/reducers.py and holds/capsules.py already apply to money).
    # Scaled to an integer in [0, 1_000_000] -- the same "integer minor
    # units" discipline this codebase uses for money, applied to a
    # probability instead of a currency.
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not (0.0 <= confidence <= 1.0):
        raise JudgeError(CONFIDENCE_OUT_OF_RANGE, f"result.confidence must be a number in [0.0, 1.0]; got {confidence!r}")
    return round(confidence * 1_000_000)


def build_judgment_capsule(
    *,
    prompt: JudgePromptDefinition,
    evidence: JudgeEvidence,
    result: ScoreResult,
    operator: str,
    developer: str,
    signer: Signer,
    session_digest: str | None = None,
    chain_parent: str | None = None,
    timestamp: str | None = None,
    action_id: str | None = None,
) -> dict:
    """Seal one judge run as a passive ``fyi`` capsule.

    ``chain_parent`` is optional and, when given, chains this judgment to
    the session-close capsule (or the last known turn) with relation
    ``"confirms"`` -- a convenience link, never a substitute for the
    evidence range recorded in ``detail`` (the chain alone can't carry a
    multi-turn evidence range; ``detail.evidence`` is the source of truth).
    """
    if not evidence.turn_capsule_ids:
        raise JudgeError(EMPTY_EVIDENCE_RANGE, "evidence.turn_capsule_ids must be non-empty -- a judgment needs an evidence range")
    if result.label not in prompt.label_set:
        raise JudgeError(
            LABEL_NOT_IN_LABEL_SET,
            f"result.label {result.label!r} is not in prompt {prompt.prompt_id!r}'s label_set {sorted(prompt.label_set)}",
        )
    confidence_micros = _confidence_micros(result.confidence)
    if evidence.target_speaker_role is not None and evidence.target_speaker_role not in SPEAKER_ROLES:
        raise JudgeError(
            INVALID_SPEAKER_ROLE_TARGET,
            f"evidence.target_speaker_role must be one of {sorted(SPEAKER_ROLES)} or None; got {evidence.target_speaker_role!r}",
        )

    evidence_detail: dict = {
        "session_id": evidence.session_id,
        "turn_capsule_ids": list(evidence.turn_capsule_ids),
    }
    if session_digest is not None:
        evidence_detail["session_digest"] = session_digest

    detail: dict = {
        "prompt_id": prompt.prompt_id,
        "prompt_digest": prompt.prompt_digest(),
        "model_id": result.model_id,
        "label": result.label,
        "confidence_micros": confidence_micros,
        "evidence": evidence_detail,
    }
    if evidence.target_speaker_role is not None:
        detail["target_speaker_role"] = evidence.target_speaker_role
    rationale_digest = _rationale_digest(result.rationale)
    if rationale_digest is not None:
        detail["rationale_digest"] = rationale_digest

    return build_event_capsule(
        operator=operator,
        developer=developer,
        signer=signer,
        event=EVENT_JUDGMENT,
        detail=detail,
        timestamp=timestamp,
        action_id=action_id or f"judge.judgment/{evidence.session_id}/{prompt.prompt_id}",
        chain_parent=chain_parent,
        chain_relation=CONFIRMS if chain_parent else None,
    )


def build_adjudication_capsule(
    *,
    judgment: dict,
    label: str,
    agrees_with_judge: bool,
    operator: str,
    developer: str,
    signer: Signer,
    rationale: str | None = None,
    timestamp: str | None = None,
    action_id: str | None = None,
) -> dict:
    """Seal one MANUAL spot-check adjudication -- a human-disposed capsule
    chained to the judgment it disposes of.

    ``judgment`` is the sealed judgment capsule dict (a ``LedgerRecord``'s
    own ``.capsule``, or a freshly-built judgment before append -- either
    way, this validates it really is a ``judge_judgment`` capsule rather
    than trusting a bare id). When ``agrees_with_judge`` is True, ``label``
    MUST equal the judgment's own label -- claiming agreement while
    recording a different label would be a silent contradiction this
    codebase's honesty invariants don't allow elsewhere and shouldn't allow
    here either.

    Cross-family automated second-opinion judging ("different-family
    option") and judge-quality folds (kappa/calibration/drift) are the full
    B3 shape, explicitly Wave 2 -- this is MANUAL adjudication only.
    """
    payload = judgment.get("asg_payload") or {}
    if payload.get("event") != EVENT_JUDGMENT:
        raise JudgeError(
            JUDGMENT_NOT_FOUND,
            f"capsule {judgment.get('capsule_id')!r} is not a {EVENT_JUDGMENT!r} capsule",
        )
    judgment_label = (payload.get("detail") or {}).get("label")
    if agrees_with_judge and label != judgment_label:
        raise JudgeError(
            ADJUDICATION_LABEL_MISMATCH,
            f"agrees_with_judge=True but label {label!r} != the judgment's own label {judgment_label!r}",
        )
    judgment_capsule_id = judgment["capsule_id"]

    decision = "accept" if agrees_with_judge else "reject"
    disposition = Disposition(
        decision=decision,
        approver="human",
        human_disposed=True,
        verdict_class=None,
        reason_digest=_rationale_digest(rationale),
    )
    action = Action(
        verb=EVENT_ADJUDICATION,
        operator=operator,
        developer=developer,
        action_type="fyi",
        action_id=action_id or f"judge.adjudication/{judgment_capsule_id}",
        timestamp=timestamp,
    )
    chain = Chain(parent_capsule_id=judgment_capsule_id, relation=CONFIRMS)
    capsule_obj = Capsule(
        spec_version=_SPEC_VERSION,
        format_version=_FORMAT_VERSION,
        action_id=action.resolved_action_id(),
        action_type="fyi",
        operator=operator,
        developer=developer,
        timestamp=action.resolved_timestamp(),
        assurance=AssuranceBlock(attestation_mode="self_attested", effect_mode="not_applicable", ledger_mode="chained"),
        disposition=disposition,
        chain=chain,
    )
    body = capsule_obj.to_dict()
    body["asg_payload"] = {
        "event": EVENT_ADJUDICATION,
        "detail": {
            "judgment_capsule_id": judgment_capsule_id,
            "label": label,
            "agrees_with_judge": agrees_with_judge,
        },
    }

    presig_digest = json_digest(body)
    body["asg_signature"] = {
        "key_id": signer.key_id,
        "alg": signer.algorithm,
        "sig": signer.sign(presig_digest),
    }

    capsule_id = compute_capsule_id(body)
    sealed = {"spec_version": body["spec_version"], "format_version": body["format_version"], "capsule_id": capsule_id}
    for k, v in body.items():
        if k not in sealed:
            sealed[k] = v
    return sealed


def build_judge_prompt_activation_capsule(
    *,
    prompt: JudgePromptDefinition,
    operator: str,
    developer: str,
    signer: Signer,
    previous_activation_capsule_id: str | None = None,
    timestamp: str | None = None,
    action_id: str | None = None,
) -> dict:
    """A judge prompt change is a policy-manifest-shaped event (B3: "judge
    prompt changes are policy-manifest events") -- same ``epoch_opens``
    chain-of-epochs shape as ``policy/activation.py``'s own
    ``build_manifest_activation_capsule``, chained to the prior prompt
    activation (or the shared ``GENESIS_PARENT`` sentinel for the first
    activation in a ledger)."""
    detail = {
        "prompt_id": prompt.prompt_id,
        "prompt_digest": prompt.prompt_digest(),
        "label_set": list(prompt.label_set),
    }
    return build_event_capsule(
        operator=operator,
        developer=developer,
        signer=signer,
        event=EVENT_PROMPT_ACTIVATED,
        detail=detail,
        timestamp=timestamp,
        action_id=action_id,
        chain_parent=previous_activation_capsule_id or GENESIS_PARENT,
        chain_relation="epoch_opens",
    )


def find_judgments_for_session(ledger: LedgerAPI, session_id: str) -> list[LedgerRecord]:
    matches = []
    for record in ledger.scan(ScanQuery(action_type="fyi")):
        payload = record.capsule.get("asg_payload") or {}
        if payload.get("event") != EVENT_JUDGMENT:
            continue
        if (payload.get("detail") or {}).get("evidence", {}).get("session_id") == session_id:
            matches.append(record)
    return matches


def find_adjudications_for_judgment(ledger: LedgerAPI, judgment_capsule_id: str) -> list[LedgerRecord]:
    matches = []
    for record in ledger.scan(ScanQuery(action_type="fyi")):
        payload = record.capsule.get("asg_payload") or {}
        if payload.get("event") != EVENT_ADJUDICATION:
            continue
        if (payload.get("detail") or {}).get("judgment_capsule_id") == judgment_capsule_id:
            matches.append(record)
    return matches


def find_latest_prompt_activation(ledger: LedgerAPI, prompt_id: str | None = None) -> LedgerRecord | None:
    """The most recently appended prompt-activation record (optionally
    filtered to one ``prompt_id`` family), or ``None`` if this ledger has
    never had one. ``scan()`` is append-ordered, so the last match wins."""
    latest: LedgerRecord | None = None
    for record in ledger.scan(ScanQuery(action_type="fyi")):
        payload = record.capsule.get("asg_payload") or {}
        if payload.get("event") != EVENT_PROMPT_ACTIVATED:
            continue
        if prompt_id is not None and (payload.get("detail") or {}).get("prompt_id") != prompt_id:
            continue
        latest = record
    return latest
