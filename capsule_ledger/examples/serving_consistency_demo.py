# SPDX-License-Identifier: Apache-2.0
"""Serving/hardware-consistency demo: "can I see your ID from before + what
are you now."

Run as ``python -m capsule_ledger.examples.serving_consistency_demo``.

**The request flow this supports.** A relying party asks a serving node two
things at once: *show me your ID from before* (a range of the node's past
serving capsules) and *what are you now* (a fresh capsule). It then runs the
``ServingConsistencyScorer`` over ``[range + now]`` and the judge harness
seals the verdict as a capsule -- "the machine said it was running X
(model/hardware) before, and Y now; the hardware must not change."

**What is net-new vs reused.** The ONLY net-new code is the scorer
(``judge/scorers/serving_consistency.py``); everything below is existing
machinery:

- capsules over the range are built by the existing
  ``conversation.exchange.build_conversation_exchange_capsule`` (the mesh-
  shaped ``model_attestation.compute_attestation`` carrier);
- the verdict is scored, pinned, and SEALED AS A CAPSULE by the existing
  ``judge.JudgeHarness`` (``run`` -> ``judge_judgment``; ``check_drift`` ->
  ``judge_drift_check``), never a hand-rolled verdict path;
- disclosure to the relying party is the existing ``capsule bundle`` CLI
  (``cli/bundle_cmd.py``) over the node's range + the fresh capsule + the
  sealed verdict -- this module does NOT reimplement bundle assembly. The
  composition is exactly the W1c pattern (build the ledger here; bundle it
  with the existing verb):

.. code-block:: console

   $ python -m capsule_ledger.examples.serving_consistency_demo --ledger ./demo-ledger
   $ capsule bundle --ledger ./demo-ledger --out serving.json --with-viewer

**Deterministic.** The scorer reads only the declared serving range (carried
as canonical JSON in the evidence text via ``serving_evidence_text``) -- no
wall-clock, no external state -- so the harness's own drift re-run over the
same range is meaningful.
"""
from __future__ import annotations

import argparse
import secrets
import tempfile
from pathlib import Path
from typing import Any

from ..conversation.exchange import build_conversation_exchange_capsule
from ..guards.signing import LocalSigner
from ..judge import JudgeEvidence, JudgeHarness, JudgePromptDefinition
from ..judge.scorers.serving_consistency import (
    LABEL_ABSENT,
    LABEL_CHANGED,
    LABEL_CONSISTENT,
    ServingConsistencyScorer,
    extract_serving_view,
    serving_evidence_text,
)
from ..ledger import LedgerStore

OPERATOR = "relying-party-desk"
DEVELOPER = "serving-consistency-demo@v1"

# The prompt is the three-state closed label set the scorer requires. Its
# digest pins exactly this rubric onto every verdict it produces (a one-char
# edit changes the digest -- the drifted-prompt guard).
SERVING_PROMPT = JudgePromptDefinition(
    prompt_id="serving.hardware_consistency/1.0.0",
    label_set=(LABEL_CONSISTENT, LABEL_CHANGED, LABEL_ABSENT),
    instructions=(
        "Given a range of a serving node's capsules (its ID from before) plus "
        "a fresh capsule (what it is now), is the serving hardware invariant "
        "across the range? Hardware-invariant fields (gpu/vram_bytes/is_soc/"
        "served_by_node_id/hostname) MUST NOT change; a change is flagged. A "
        "model/quant change is a disclosed, attributable delta. Absent when no "
        "comparable serving field is present."
    ),
)


def _exchange(store: LedgerStore, signer: LocalSigner, *, exchange_id: str, node_id: str, gpu: str, model_id: str, quant: str, chain_parent: str | None) -> Any:
    """Seal one serving capsule via the EXISTING exchange builder -- its
    ``compute_attestation`` carries the serving provenance the scorer reads.
    ``served_by_node_id``/``gpu`` ride the ``hardware`` field's neighbours in
    the same block (the mesh serving_provenance keys)."""
    capsule = build_conversation_exchange_capsule(
        session_id=node_id,
        exchange_id=exchange_id,
        messages=[{"role": "user", "content": "ping"}, {"role": "assistant", "content": "pong"}],
        model_id=model_id,
        provider="mesh",
        operator=OPERATOR,
        developer=DEVELOPER,
        signer=signer,
        quant=quant,
        hardware=gpu,
        chain_parent=chain_parent,
        chain_relation="confirms" if chain_parent else None,
    )
    # Fold the mesh serving_provenance keys the scorer names into the same
    # compute_attestation block, then re-seal via the store's append path.
    capsule["model_attestation"]["compute_attestation"]["served_by_node_id"] = node_id
    capsule["model_attestation"]["compute_attestation"]["gpu"] = gpu
    # Re-sign after the edit so the capsule stays verifiable (same digest-then-
    # sign discipline the builder uses).
    from agent_action_capsule import compute_capsule_id, json_digest

    body = {k: v for k, v in capsule.items() if k not in ("capsule_id", "asg_signature")}
    body["asg_signature"] = {"key_id": signer.key_id, "alg": signer.algorithm, "sig": signer.sign(json_digest(body))}
    body["capsule_id"] = compute_capsule_id(body)
    return store.append(body, consequential=False)


def _harness(store: LedgerStore, signer: LocalSigner) -> JudgeHarness:
    return JudgeHarness(
        ledger=store,
        prompt=SERVING_PROMPT,
        scorer=ServingConsistencyScorer(),
        operator=OPERATOR,
        developer=DEVELOPER,
        signer_provider=lambda: signer,
    )


def run_flow(ledger_path: Path) -> dict[str, Any]:
    store = LedgerStore(ledger_path)
    signer = LocalSigner(key_id="demo-relying-party-key", secret=secrets.token_bytes(32))
    try:
        # --- "your ID from before": a range of the node's past capsules ---
        r0 = _exchange(store, signer, exchange_id="e0", node_id="node-alpha", gpu="nvidia-a100", model_id="llama-3-70b", quant="q4", chain_parent=None)
        r1 = _exchange(store, signer, exchange_id="e1", node_id="node-alpha", gpu="nvidia-a100", model_id="llama-3-70b", quant="q4", chain_parent=r0.capsule_id)
        # --- "what you are now": a fresh capsule, SAME hardware (consistent) ---
        now_ok = _exchange(store, signer, exchange_id="e2", node_id="node-alpha", gpu="nvidia-a100", model_id="llama-3-70b", quant="q4", chain_parent=r1.capsule_id)

        consistent_range = [r0.capsule, r1.capsule, now_ok.capsule]
        evidence_ok = JudgeEvidence(
            session_id="node-alpha",
            turn_capsule_ids=tuple(c["capsule_id"] for c in consistent_range),
            evidence_text=serving_evidence_text(consistent_range),
        )
        harness = _harness(store, signer)
        verdict_ok = harness.run(evidence=evidence_ok, chain_parent=now_ok.capsule_id)

        # --- the flagged case: a fresh capsule on DIFFERENT hardware ---
        now_bad = _exchange(store, signer, exchange_id="e3", node_id="node-BETA", gpu="apple-m3-max", model_id="llama-3-70b", quant="q4", chain_parent=r1.capsule_id)
        flagged_range = [r0.capsule, r1.capsule, now_bad.capsule]
        evidence_bad = JudgeEvidence(
            session_id="node-alpha",
            turn_capsule_ids=tuple(c["capsule_id"] for c in flagged_range),
            evidence_text=serving_evidence_text(flagged_range),
        )
        verdict_bad = harness.run(evidence=evidence_bad, chain_parent=now_bad.capsule_id)

        # --- drift re-run over the SAME flagged range (deterministic) ---
        drift = harness.check_drift(judgment=verdict_bad.capsule, evidence=evidence_bad)

        return {
            "consistent_verdict": verdict_ok.capsule["asg_payload"]["detail"]["label"],
            "consistent_verifies": store.verify(verdict_ok.capsule_id).ok,
            "flagged_verdict": verdict_bad.capsule["asg_payload"]["detail"]["label"],
            "flagged_verifies": store.verify(verdict_bad.capsule_id).ok,
            "flagged_rationale": verdict_bad.capsule["asg_payload"]["detail"].get("rationale_digest") is not None,
            "drift_verifies": store.verify(drift.capsule_id).ok,
            "drift_flag": drift.capsule["asg_payload"]["detail"]["drifted"],
            "before_view": extract_serving_view(r0.capsule),
            "now_ok_view": extract_serving_view(now_ok.capsule),
            "now_bad_view": extract_serving_view(now_bad.capsule),
        }
    finally:
        store.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", default=None, help="ledger dir (default: a temp dir)")
    args = parser.parse_args(argv)

    ledger_path = Path(args.ledger) if args.ledger else Path(tempfile.mkdtemp(prefix="serving-demo-"))
    out = run_flow(ledger_path)

    print("=== serving/hardware-consistency request flow ===")
    print(f"ledger: {ledger_path}")
    print()
    print("your ID from before :", out["before_view"])
    print("what you are now (ok):", out["now_ok_view"])
    print(f"  -> verdict = {out['consistent_verdict']!r} (verifies={out['consistent_verifies']})")
    print()
    print("what you are now (bad):", out["now_bad_view"])
    print(f"  -> verdict = {out['flagged_verdict']!r} (verifies={out['flagged_verifies']}) -- HARDWARE FLAG")
    print(f"  -> drift re-run over same range: drifted={out['drift_flag']} (verifies={out['drift_verifies']})")
    print()
    print("disclose to the relying party with the EXISTING bundle CLI, e.g.:")
    print(f"  capsule bundle --ledger {ledger_path} --out serving.json --with-viewer")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
