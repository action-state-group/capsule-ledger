# SPDX-License-Identifier: Apache-2.0
"""``capsule judge`` verbs: ``run`` (score an evidence range against a
digest-pinned prompt and append the resulting judgment capsule) and
``adjudicate`` (record a MANUAL spot-check human disposition of an existing
judgment). Neither verb reaches into ``guards.engine`` -- the judge is
structurally kept out of the enforcement path (B3).

``run``'s default scorer is DeepEval (``--scorer deepeval``, per the
Outcome Compiler doc's BYOM default) -- this makes a real model call and
needs an API key configured however DeepEval's own model backend expects
(e.g. ``OPENAI_API_KEY``), same as any DeepEval user. ``--scorer static``
is the no-network, no-key deterministic reference (``judge/scorers/static.py``)
-- useful for demos and scripted runs where the label is already known.
"""
from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

from ..envcompat import env_get
from ..guards.signing import LocalSigner
from ..ledger import LedgerStore
from .init_cmds import _KEY_ID_ENV, _KEY_ID_ENV_LEGACY, _SECRET_ENV, _SECRET_ENV_LEGACY

__all__ = ["add_parser"]


def _signer(args: argparse.Namespace) -> LocalSigner:
    key_id = args.key_id or env_get(_KEY_ID_ENV, _KEY_ID_ENV_LEGACY)
    secret_text = args.secret or env_get(_SECRET_ENV, _SECRET_ENV_LEGACY)
    if key_id is None:
        key_id = f"{args.operator}-judge-key"
    if secret_text is None:
        secret_text = secrets.token_hex(32)
    return LocalSigner(key_id=key_id, secret=secret_text.encode("utf-8"))


def _cmd_judge_run(args: argparse.Namespace) -> int:
    from ..conversation.capsules import find_session_close, find_session_turns
    from ..judge import JudgeEvidence, JudgeHarness
    from ..judge.errors import JudgeError
    from ..judge.loader import load_prompt_file
    from ..judge.scorers.static import StaticScorer

    try:
        prompt = load_prompt_file(args.prompt)
    except JudgeError as exc:
        print(f"capsule judge run: prompt failed to load ({exc.reason}): {exc}", file=sys.stderr)
        return 1

    if args.evidence_file:
        evidence_text = Path(args.evidence_file).read_text(encoding="utf-8")
    elif args.evidence_text is not None:
        evidence_text = args.evidence_text
    else:
        print("capsule judge run: one of --evidence-text/--evidence-file is required", file=sys.stderr)
        return 1

    if args.scorer == "static":
        if args.static_label is None or args.static_confidence is None:
            print("capsule judge run: --scorer static requires --static-label and --static-confidence", file=sys.stderr)
            return 1
        scorer = StaticScorer(
            responses={evidence_text: (args.static_label, args.static_confidence)}, model_id="cli-static-scorer"
        )
    else:
        from ..judge.scorers.deepeval_scorer import DeepEvalScorer

        try:
            scorer = DeepEvalScorer(model=args.model)
        except JudgeError as exc:
            print(f"capsule judge run: {exc.reason}: {exc}", file=sys.stderr)
            return 1

    ledger = LedgerStore(args.ledger)
    try:
        turn_capsule_ids = tuple(args.turn_capsule_id) if args.turn_capsule_id else None
        session_digest = None
        chain_parent = None
        close_record = find_session_close(ledger, args.session)
        if close_record is not None:
            session_digest = close_record.capsule["asg_payload"]["detail"]["session_digest"]
            chain_parent = close_record.capsule_id
        if turn_capsule_ids is None:
            turns = find_session_turns(ledger, args.session)
            if not turns:
                print(f"capsule judge run: no turns found for session {args.session!r}; pass --turn-capsule-id explicitly", file=sys.stderr)
                return 1
            turn_capsule_ids = tuple(t.capsule_id for t in turns)

        evidence = JudgeEvidence(
            session_id=args.session,
            turn_capsule_ids=turn_capsule_ids,
            evidence_text=evidence_text,
            target_speaker_role=args.speaker_role,
        )
        harness = JudgeHarness(
            ledger=ledger,
            prompt=prompt,
            scorer=scorer,
            operator=args.operator,
            developer=args.developer,
            signer_provider=lambda: _signer(args),
        )
        try:
            record = harness.run(evidence=evidence, session_digest=session_digest, chain_parent=chain_parent)
        except JudgeError as exc:
            print(f"capsule judge run: {exc.reason}: {exc}", file=sys.stderr)
            return 1
    finally:
        ledger.close()

    detail = record.capsule["asg_payload"]["detail"]
    print(f"judgment recorded: {record.capsule_id}")
    print(f"  prompt:     {detail['prompt_id']} ({detail['prompt_digest']})")
    print(f"  model:      {detail['model_id']}")
    print(f"  label:      {detail['label']} (confidence {detail['confidence_micros'] / 1_000_000:.3f})")
    print(f"  evidence:   {len(detail['evidence']['turn_capsule_ids'])} turn(s) over session {args.session!r}")
    return 0


def _cmd_judge_adjudicate(args: argparse.Namespace) -> int:
    from ..judge import build_adjudication_capsule
    from ..judge.errors import JudgeError

    ledger = LedgerStore(args.ledger)
    try:
        judgment_record = ledger.fetch(args.judgment)
        if judgment_record is None:
            print(f"capsule judge adjudicate: no such capsule {args.judgment!r} in ledger {args.ledger}", file=sys.stderr)
            return 1

        try:
            capsule = build_adjudication_capsule(
                judgment=judgment_record.capsule,
                label=args.label,
                agrees_with_judge=args.agree,
                operator=args.operator,
                developer=args.developer,
                signer=_signer(args),
                rationale=args.rationale,
            )
        except JudgeError as exc:
            print(f"capsule judge adjudicate: {exc.reason}: {exc}", file=sys.stderr)
            return 1
        record = ledger.append(capsule, consequential=False)
    finally:
        ledger.close()

    detail = record.capsule["asg_payload"]["detail"]
    disposition = record.capsule["disposition"]
    print(f"adjudication recorded: {record.capsule_id}")
    print(f"  judgment:   {detail['judgment_capsule_id']}")
    print(f"  decision:   {disposition['decision']} (human_disposed={disposition['human_disposed']})")
    print(f"  label:      {detail['label']}")
    return 0


def add_parser(sub: argparse._SubParsersAction) -> argparse.ArgumentParser:
    judge = sub.add_parser("judge", help="the judge harness: score evidence against a digest-pinned prompt, and adjudicate")
    judge_sub = judge.add_subparsers(dest="judge_command")
    judge.set_defaults(judge_parser=judge)

    p_run = judge_sub.add_parser("run", help="score an evidence range against a prompt and append a judgment capsule")
    p_run.add_argument("--ledger", required=True, help="ledger store directory")
    p_run.add_argument("--prompt", required=True, help="judge prompt definition YAML (JudgePromptDefinition)")
    p_run.add_argument("--session", required=True, help="conversation session id (B5 conversation profile)")
    p_run.add_argument(
        "--turn-capsule-id", action="append", default=[],
        help="evidence-range turn capsule id (repeatable; default: every turn found for --session, in order)",
    )
    p_run.add_argument("--speaker-role", default=None, help="target one declared speaker role (user/assistant/human-agent); default: whole session")
    p_run.add_argument("--evidence-text", default=None, help="evidence content, given directly")
    p_run.add_argument("--evidence-file", default=None, help="evidence content, read from a file")
    p_run.add_argument("--scorer", choices=["deepeval", "static"], default="deepeval", help="Scorer backend (default: deepeval)")
    p_run.add_argument("--model", default=None, help="model id override passed to the deepeval scorer")
    p_run.add_argument("--static-label", default=None, help="--scorer static: the label to emit")
    p_run.add_argument("--static-confidence", type=float, default=None, help="--scorer static: the confidence (0.0-1.0) to emit")
    p_run.add_argument("--operator", default="local", help="operator identity for the judgment capsule")
    p_run.add_argument("--developer", default="capsule-judge-tool", help="developer identity for the judgment capsule")
    p_run.add_argument("--key-id", default=None, help="signing key id")
    p_run.add_argument("--secret", default=None, help="signing key secret")
    p_run.set_defaults(func=_cmd_judge_run)

    p_adj = judge_sub.add_parser("adjudicate", help="record a MANUAL spot-check adjudication of an existing judgment")
    p_adj.add_argument("--ledger", required=True, help="ledger store directory")
    p_adj.add_argument("--judgment", required=True, help="the judgment capsule_id (or an unambiguous prefix) being adjudicated")
    p_adj.add_argument("--label", required=True, help="the human-disposed label")
    agree_group = p_adj.add_mutually_exclusive_group(required=True)
    agree_group.add_argument("--agree", dest="agree", action="store_true", help="--label must match the judgment's own label")
    agree_group.add_argument("--override", dest="agree", action="store_false", help="--label replaces the judgment's own label")
    p_adj.add_argument("--rationale", default=None, help="optional free-text rationale (digested, never stored raw)")
    p_adj.add_argument("--operator", default="local", help="operator identity for the adjudication capsule")
    p_adj.add_argument("--developer", default="capsule-judge-tool", help="developer identity for the adjudication capsule")
    p_adj.add_argument("--key-id", default=None, help="signing key id")
    p_adj.add_argument("--secret", default=None, help="signing key secret")
    p_adj.set_defaults(func=_cmd_judge_adjudicate)

    return judge
