# SPDX-License-Identifier: Apache-2.0
"""Deterministic conversation-to-outcome demo: the W1c ("B6a MVP EXIT") chain.

Run as ``python -m capsule_ledger.examples.conversation_outcome_demo``.

This is the small, hand-scripted proof that the three Wave-1 tracks compose
into ONE chain end to end -- ``ledger-lane/inbox.md``'s ``[ldg-outcomes-batch]``
W1c, distinct from the flagship B6 demo (Wave 2, tau2-bench via
record-grounding-bench, the outcomes-schema-driven pack/fold machinery). Here
the "pack" and the "attainment fold" are both hand-written Python, not a
declared ``outcomes[]`` schema entry validated against
``folds/definition.py``'s digest-pinned fold-definition engine -- that
machinery is explicitly out of scope until
``[ldg-outcome-declaration-schema]`` lands (Wave 2).

**The chain, one capsule family at a time:**

1. **Conversation** (``capsule_ledger.conversation``) -- a
   ``ConversationSession`` records a short, scripted workforce-IT-support
   exchange turn by turn (a user reporting a sign-in block, an assistant
   proposing to enable MFA, the user agreeing, the assistant confirming it
   submitted the request), sealing each turn AT TURN TIME with only its
   ``content_digest`` on the capsule (H2: content never enters the record),
   then closes the session into one Merkle session digest.
2. **Judged agreement** (``capsule_ledger.judge``) -- a hand-written
   ``JudgePromptDefinition`` (``conversation.agreement_reached/1.0.0``) is
   scored against the whole turn range by ``StaticScorer`` -- deterministic,
   no network call, no model API key, the same "no live model needed for a
   demo/test" seam ``judge/scorers/static.py`` exists for. The resulting
   judgment capsule chains to the session-close capsule (``relation=
   "confirms"``) -- this is the MODEL-ASSISTED evaluation class. A MANUAL
   spot-check adjudication (``JudgeHarness.adjudicate``) then chains to the
   judgment, agreeing with its label -- the MANUAL evaluation class.
3. **Mock-IdP confirmed** (``capsule_ledger.confirm``) -- once the
   conversation has an agreement, ``ConfirmIngestEngine`` polls a
   ``MockIdPConnector`` seeded with "MFA now enabled for this employee" and
   seals a fulfillment capsule chained **to the judgment capsule itself**
   (``relation="confirms"``, ``effect.effect_attestation="runtime_claimed"``
   per REGISTRY.md #5 -- a connector read, never stronger) -- this is the
   DETERMINISTIC evaluation class: either the third system confirms it or it
   doesn't, no model in the loop. Chaining the confirmation to the judgment
   (rather than to some separate synthetic "commitment" capsule) is what
   makes the ledger literally spell out conversation -> agreement ->
   confirmed as one walkable chain.
4. **Hand-written attainment fold** (``build_attainment_fold`` below) -- a
   plain Python scan over the ledger, NOT the declarative
   ``folds/definition.py`` engine: how many sessions were judged, how many
   reached agreement, how many of those were confirmed, each field tagged
   with its own evaluation class, coverage reported honestly (n of m --
   an unjudged or unconfirmed session is never imputed into either
   numerator).

**What this module deliberately doesn't do:** call ``capsule bundle``
itself. Bundling a slice of a ledger into a self-contained, offline-
verifiable, permalink-carrying artifact is already a general CLI verb
(``cli/bundle_cmd.py``) that operates on any ledger -- the W1c acceptance
bar is explicitly "the EXISTING bundle in the EXISTING viewer", so the
composition is:

.. code-block:: console

   $ python -m capsule_ledger.examples.conversation_outcome_demo --out /tmp/demo-ledger.jsonl
   $ capsule bundle --ledger /tmp/demo-ledger.jsonl --out /tmp/demo-bundle.json --with-viewer

which prints a ``verify.agentactioncapsule.org/bundle#...`` permalink (and
writes a self-contained offline HTML copy next to it) that a stranger can
open cold and see every capsule in this chain -- turns, session-close,
judgment, adjudication, confirmation -- with their raw ``asg_payload``/
``effect``/``disposition`` fields, i.e. the evaluation-class-bearing detail,
visible per record. (Registry-driven semantic labels for outcome
conventions are a separate, still-gated task,
``[ldg-registry-driven-viewer]``'s outcomes[] half -- this demo does not
depend on it.)

**Determinism.** Same discipline as ``examples/two_agents.py``: an explicit
``_DeterministicClock`` (no wall-clock), seeded HMAC signing keys, no random
material anywhere -- the same ``--seed`` reproduces a byte-identical ledger.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from ..confirm import CONFIRMS as CONFIRM_RELATION
from ..confirm import ConfirmIngestEngine, ConfirmStatus
from ..confirm.connectors import MockIdPConnector
from ..conversation import EVENT_SESSION_CLOSE, ConversationSession
from ..guards.signing import LocalSigner
from ..judge import (
    EVENT_ADJUDICATION,
    EVENT_JUDGMENT,
    JudgeEvidence,
    JudgeHarness,
    JudgePromptDefinition,
)
from ..judge.scorers.static import StaticScorer
from ..ledger import LedgerRecord, LedgerStore

__all__ = ["DemoResult", "run_demo", "build_attainment_fold", "main"]

DEFAULT_FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures" / "conversation_outcome_demo_ledger.jsonl"
)

DEFAULT_SEED = 20260812
BASE_TIMESTAMP = "2026-08-12T09:00:00Z"
CLOCK_STEP_SECONDS = 11

OPERATOR = "acme-corp"
ASSISTANT_DEVELOPER = "security-assistant@v1"

SESSION_ID = "session-mfa-remediation-demo-001"
EMPLOYEE_SUBJECT = "employee-4471"
MFA_PREDICATE = "mfa_enabled"

AGREEMENT_PROMPT_ID = "conversation.agreement_reached/1.0.0"
AGREEMENT_LABEL_SET = ("agreement_reached", "no_agreement", "escalation_needed")

# The scripted transcript -- plaintext lives only here, in the demo script;
# only each turn's sha256 digest ever reaches a capsule (H2: content never
# enters the record, in any mode).
TRANSCRIPT: tuple[tuple[str, str], ...] = (
    ("user", "My laptop keeps blocking sign-in and IT said I need to enable MFA myself."),
    ("assistant", "I can walk you through it now -- want me to enable MFA on your account?"),
    ("user", "Yes, let's do it."),
    ("assistant", "Done -- I've submitted the MFA enrollment request and will confirm once it's active."),
)


class _DeterministicClock:
    """A fixed, non-wall-clock timestamp source (mirrors
    ``examples/two_agents.py``'s own clock -- see that module for why)."""

    def __init__(self, start: str, step_seconds: int) -> None:
        self._current = datetime.fromisoformat(start.replace("Z", "+00:00"))
        self._step = timedelta(seconds=step_seconds)

    def next(self) -> str:
        ts = self._current
        self._current += self._step
        return ts.isoformat().replace("+00:00", "Z")


def _seeded_secret(seed: int, label: str) -> bytes:
    return hashlib.sha256(f"conversation-outcome-demo/{seed}/{label}".encode()).digest()


def _seeded_uuid(seed: int, label: str) -> uuid.UUID:
    digest = hashlib.sha256(f"conversation-outcome-demo/{seed}/{label}".encode()).digest()
    return uuid.UUID(bytes=digest[:16])


@contextmanager
def _pinned_uuid4(fixed_uuid: uuid.UUID) -> Iterator[None]:
    """Pin ``uuid.uuid4()`` for the duration of one call.
    ``confirm/capsule.py``'s ``build_confirm_capsule`` generates its own
    ``action_id`` via a bare ``uuid.uuid4()`` (``ConfirmIngestEngine.ingest``
    has no ``action_id`` override in its public API) -- without pinning it,
    the same ``--seed`` would still produce a different confirmation capsule
    id on every run, same non-determinism ``examples/two_agents.py`` pins
    around its own ``capsule_emit.emit()`` call."""
    real_uuid4 = uuid.uuid4
    uuid.uuid4 = lambda: fixed_uuid
    try:
        yield
    finally:
        uuid.uuid4 = real_uuid4


def _content_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _transcript_evidence_text() -> str:
    """One deterministic string over the whole transcript -- what the
    (static, no-model) scorer is keyed against. A real ``Scorer`` (e.g.
    ``DeepEvalScorer``) would instead resolve each turn's plaintext from
    wherever the caller's own payload store keeps it, keyed by the
    capsule's own ``content_digest`` -- this demo inlines that lookup since
    it already has the plaintext in hand."""
    return "\n".join(f"{role}: {text}" for role, text in TRANSCRIPT)


@dataclass(frozen=True)
class DemoResult:
    """Everything a caller (the CLI, or a test) needs, without re-deriving
    it: every record in append order, capsule ids keyed by stable step
    name, and the hand-written attainment fold computed at the end."""

    records: tuple[LedgerRecord, ...]
    capsule_ids: dict[str, str]
    fold: dict = field(default_factory=dict)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(f"conversation-outcome demo: {message}")


def _run_chain(ledger: LedgerStore, *, seed: int) -> DemoResult:
    clock = _DeterministicClock(BASE_TIMESTAMP, CLOCK_STEP_SECONDS)
    conversation_signer = LocalSigner(key_id="security-assistant-conv-key", secret=_seeded_secret(seed, "conversation"))
    confirm_signer = LocalSigner(key_id="confirm-ingester-key", secret=_seeded_secret(seed, "confirm"))

    capsule_ids: dict[str, str] = {}

    # -- 1. Conversation: record every turn, then close the session --
    session = ConversationSession(
        ledger=ledger,
        session_id=SESSION_ID,
        operator=OPERATOR,
        developer=ASSISTANT_DEVELOPER,
        signer_provider=lambda: conversation_signer,
    )
    for turn_index, (role, text) in enumerate(TRANSCRIPT):
        record = session.record_turn(speaker_role=role, content_digest=_content_digest(text), timestamp=clock.next())
        capsule_ids[f"turn_{turn_index}_{role}"] = record.capsule_id
    close_record = session.close(timestamp=clock.next())
    _require(
        close_record.capsule["asg_payload"]["event"] == EVENT_SESSION_CLOSE,
        f"session close capsule has the wrong event ({close_record.capsule['asg_payload']['event']!r})",
    )
    capsule_ids["session_close"] = close_record.capsule_id
    session_digest = close_record.capsule["asg_payload"]["detail"]["session_digest"]

    # -- 2. Judged agreement: StaticScorer, deterministic, no network -- then a manual spot-check --
    prompt = JudgePromptDefinition(
        prompt_id=AGREEMENT_PROMPT_ID,
        label_set=AGREEMENT_LABEL_SET,
        instructions=(
            "Read the full conversation transcript. Label 'agreement_reached' if the user "
            "affirmatively agreed to take the proposed remedial action; 'no_agreement' if they "
            "declined or the conversation ended without a clear yes; 'escalation_needed' if the "
            "user asked for a human."
        ),
    )
    evidence_text = _transcript_evidence_text()
    scorer = StaticScorer(
        responses={evidence_text: ("agreement_reached", 0.93)},
        model_id="static-scorer/conversation-outcome-demo",
    )
    harness = JudgeHarness(
        ledger=ledger,
        prompt=prompt,
        scorer=scorer,
        operator=OPERATOR,
        developer=ASSISTANT_DEVELOPER,
        signer_provider=lambda: conversation_signer,
    )
    turn_capsule_ids = tuple(capsule_ids[f"turn_{i}_{role}"] for i, (role, _) in enumerate(TRANSCRIPT))
    judgment_record = harness.run(
        evidence=JudgeEvidence(session_id=SESSION_ID, turn_capsule_ids=turn_capsule_ids, evidence_text=evidence_text),
        session_digest=session_digest,
        chain_parent=close_record.capsule_id,
        timestamp=clock.next(),
    )
    _require(
        judgment_record.capsule["asg_payload"]["event"] == EVENT_JUDGMENT,
        "judgment capsule has the wrong event",
    )
    judgment_label = judgment_record.capsule["asg_payload"]["detail"]["label"]
    _require(judgment_label == "agreement_reached", f"expected the judge to reach 'agreement_reached', got {judgment_label!r}")
    capsule_ids["judgment"] = judgment_record.capsule_id

    adjudication_record = harness.adjudicate(
        judgment=judgment_record.capsule,
        label="agreement_reached",
        agrees_with_judge=True,
        rationale="spot-check: transcript matches the labeled agreement",
        timestamp=clock.next(),
    )
    _require(
        adjudication_record.capsule["asg_payload"]["event"] == EVENT_ADJUDICATION,
        "adjudication capsule has the wrong event",
    )
    _require(
        adjudication_record.capsule["disposition"]["human_disposed"] is True,
        "adjudication capsule must be human_disposed",
    )
    capsule_ids["adjudication"] = adjudication_record.capsule_id

    # -- 3. Mock-IdP confirmed: chained to the judgment capsule itself, so
    #    the ledger spells out conversation -> agreement -> confirmed as one
    #    walkable chain, not a side channel. --
    connector = MockIdPConnector()
    connector.set_state(
        subject=EMPLOYEE_SUBJECT,
        predicate=MFA_PREDICATE,
        status="confirmed",
        external_ref="idp-evt-mfa-4471-001",
        observed_at=clock.next(),
    )
    confirm_engine = ConfirmIngestEngine(ledger=ledger, connector=connector, signer_provider=lambda: confirm_signer)
    with _pinned_uuid4(_seeded_uuid(seed, "confirmation")):
        confirm_decision = confirm_engine.ingest(judgment_record.capsule_id, subject=EMPLOYEE_SUBJECT, predicate=MFA_PREDICATE)
    _require(confirm_decision.status == ConfirmStatus.RECORDED, f"expected the mock IdP confirmation to record, got {confirm_decision.status}")
    _require(confirm_decision.capsule["chain"]["parent_capsule_id"] == judgment_record.capsule_id, "confirmation must chain to the judgment capsule")
    _require(confirm_decision.capsule["chain"]["relation"] == CONFIRM_RELATION, "confirmation must use the 'confirms' chain relation")
    capsule_ids["confirmation"] = confirm_decision.capsule["capsule_id"]

    records = tuple(ledger.scan())
    fold = build_attainment_fold(ledger)
    return DemoResult(records=records, capsule_ids=capsule_ids, fold=fold)


def build_attainment_fold(ledger) -> dict:
    """A hand-written attainment fold: a plain scan over the ledger, never
    the declarative ``folds/definition.py``/``folds/engine.py`` machinery
    (that reads a DIGEST-PINNED fold definition against a DECLARED outcome
    schema -- both explicitly Wave 2, ``[ldg-outcome-declaration-schema]``).

    Reports, per conversation session found in the ledger: whether it was
    judged (MODEL-ASSISTED), whether a human spot-checked that judgment
    (MANUAL), turns-to-agreement (DETERMINISTIC), and whether the agreed
    remediation was independently confirmed by an external system
    (DETERMINISTIC). Aggregate coverage lines are honest about what was
    and wasn't judged/confirmed -- an unjudged or unconfirmed session is
    never imputed into a numerator, only left out of it, same discipline
    the fold engine's own spec enforces for declared folds.
    """
    records = list(ledger.scan())

    def _payload(record: LedgerRecord) -> dict:
        return record.capsule.get("asg_payload") or {}

    def _chain_parent(record: LedgerRecord) -> str | None:
        return (record.capsule.get("chain") or {}).get("parent_capsule_id")

    def _chain_relation(record: LedgerRecord) -> str | None:
        return (record.capsule.get("chain") or {}).get("relation")

    session_closes = [r for r in records if _payload(r).get("event") == EVENT_SESSION_CLOSE]

    sessions: list[dict] = []
    for close in session_closes:
        detail = _payload(close)["detail"]
        session_id = detail["session_id"]
        turn_count = detail["turn_count"]

        judgment = next(
            (r for r in records if _payload(r).get("event") == EVENT_JUDGMENT and _chain_parent(r) == close.capsule_id),
            None,
        )

        agreement_entry: dict | None = None
        adjudication_entry: dict | None = None
        remediation_entry: dict | None = None

        if judgment is not None:
            jdetail = _payload(judgment)["detail"]
            agreement_entry = {
                "evaluation_class": "model-assisted",
                "judgment_capsule_id": judgment.capsule_id,
                "label": jdetail["label"],
                "confidence": jdetail["confidence_micros"] / 1_000_000,
                "model_id": jdetail["model_id"],
            }

            adjudication = next(
                (
                    r
                    for r in records
                    if _payload(r).get("event") == EVENT_ADJUDICATION
                    and _payload(r).get("detail", {}).get("judgment_capsule_id") == judgment.capsule_id
                ),
                None,
            )
            if adjudication is not None:
                adetail = _payload(adjudication)["detail"]
                adjudication_entry = {
                    "evaluation_class": "manual",
                    "adjudication_capsule_id": adjudication.capsule_id,
                    "label": adetail["label"],
                    "agrees_with_judge": adetail["agrees_with_judge"],
                    "human_disposed": adjudication.capsule["disposition"]["human_disposed"],
                }

            fulfillment = next(
                (
                    r
                    for r in records
                    if _chain_parent(r) == judgment.capsule_id
                    and _chain_relation(r) == CONFIRM_RELATION
                    and _payload(r).get("connector_type")
                ),
                None,
            )
            if fulfillment is not None:
                effect = fulfillment.capsule.get("effect") or {}
                remediation_entry = {
                    "evaluation_class": "deterministic",
                    "confirm_capsule_id": fulfillment.capsule_id,
                    "effect_status": effect.get("status"),
                    "effect_attestation": effect.get("effect_attestation"),
                    "connector_type": _payload(fulfillment)["connector_type"],
                }

        sessions.append(
            {
                "session_id": session_id,
                "efficiency": {"evaluation_class": "deterministic", "turns_to_agreement": turn_count},
                "agreement": agreement_entry,
                "adjudication": adjudication_entry,
                "remediation": remediation_entry,
            }
        )

    sessions_total = len(sessions)
    sessions_judged = sum(1 for s in sessions if s["agreement"] is not None)
    agreements_reached = sum(1 for s in sessions if s["agreement"] and s["agreement"]["label"] == "agreement_reached")
    remediations_confirmed = sum(
        1 for s in sessions if s["remediation"] is not None and s["remediation"]["effect_status"] == "confirmed"
    )

    return {
        "sessions_total": sessions_total,
        "sessions_judged": sessions_judged,
        "coverage_judged": f"{sessions_judged} of {sessions_total} sessions judged",
        "agreements_reached": agreements_reached,
        "remediations_confirmed": remediations_confirmed,
        "coverage_confirmed": f"{remediations_confirmed} of {agreements_reached} judged agreements confirmed",
        "sessions": sessions,
    }


def run_demo(
    *,
    local_store_dir: str | os.PathLike | None,
    seed: int = DEFAULT_SEED,
    fixture_out: str | os.PathLike | None = None,
) -> DemoResult:
    """Run the full chain once against a fresh ``LedgerStore`` and return the
    result. Every record is scanned back off the store (not accumulated by
    hand) before it closes, so ``records``/the fold are exactly what a
    fresh reader would see -- and if ``fixture_out`` is given, exactly what
    gets exported."""
    import shutil
    import tempfile

    cleanup_dir: Path | None = None
    if local_store_dir is None:
        local_store_dir = tempfile.mkdtemp(prefix="capsule-ledger-conversation-outcome-demo-")
        cleanup_dir = Path(local_store_dir)

    store = LedgerStore(local_store_dir)
    try:
        result = _run_chain(store, seed=seed)
    finally:
        store.close()
        if cleanup_dir is not None:
            shutil.rmtree(cleanup_dir, ignore_errors=True)

    if fixture_out is not None:
        _export_fixture(result.records, Path(fixture_out))

    return result


def _export_fixture(records: tuple[LedgerRecord, ...], path: Path) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record.capsule, separators=(",", ":")) + "\n")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m capsule_ledger.examples.conversation_outcome_demo",
        description="Deterministic conversation -> judged agreement -> mock-IdP confirmed demo (see module docstring).",
    )
    parser.add_argument(
        "--local-store-dir",
        default=os.environ.get("CAPSULE_LEDGER_DEMO_STORE_DIR"),
        help="Directory for the local LedgerStore. Default: a fresh temp dir, removed after the run.",
    )
    parser.add_argument(
        "--out",
        default=os.environ.get("CAPSULE_LEDGER_DEMO_OUT", str(DEFAULT_FIXTURE_PATH)),
        help=f"Path to write the flat JSONL fixture ledger. Default: {DEFAULT_FIXTURE_PATH}. Pass '' to skip writing.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=int(os.environ.get("CAPSULE_LEDGER_DEMO_SEED", DEFAULT_SEED)),
        help="Deterministic seed for the signing keys -- same seed reproduces byte-identical output.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    fixture_out = args.out if args.out else None
    result = run_demo(local_store_dir=args.local_store_dir, seed=args.seed, fixture_out=fixture_out)

    print(f"conversation-outcome demo: {len(result.records)} capsule(s) recorded, seed={args.seed}")
    for name, capsule_id in result.capsule_ids.items():
        print(f"  {name:<18} {capsule_id[:16]}…")
    print()
    print("hand-written attainment fold:")
    print(f"  {result.fold['coverage_judged']}")
    print(f"  {result.fold['coverage_confirmed']}")
    for session in result.fold["sessions"]:
        print(f"  session {session['session_id']!r}:")
        print(f"    efficiency   [deterministic]   turns_to_agreement={session['efficiency']['turns_to_agreement']}")
        if session["agreement"]:
            a = session["agreement"]
            print(f"    agreement    [model-assisted]  label={a['label']!r} confidence={a['confidence']:.2f}")
        if session["adjudication"]:
            adj = session["adjudication"]
            print(f"    adjudication [manual]          agrees_with_judge={adj['agrees_with_judge']}")
        if session["remediation"]:
            r = session["remediation"]
            print(f"    remediation  [deterministic]   status={r['effect_status']!r} attestation={r['effect_attestation']!r}")
    if fixture_out:
        print()
        print(f"fixture written to {fixture_out}")
        print(f"next: capsule bundle --ledger {fixture_out} --out <bundle.json> --with-viewer")
    return 0


if __name__ == "__main__":
    sys.exit(main())
