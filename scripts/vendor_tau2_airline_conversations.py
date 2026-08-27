# SPDX-License-Identifier: Apache-2.0
"""Regenerates capsule_ledger/examples/data/tau2_airline/tau2_conversations_*.jsonl.

Companion to ``vendor_tau2_airline_reference_data.py``, not a replacement for it.
That script flattens tool-call events only (span_start/tool_call/span_end), which
is everything ``examples/tau2_airline_reference.py``'s guard replay needs, but is
insufficient for ``[ldg-airline-engagement-pack]``'s claims A1/A3/A5/A7 -- those
read the AGENT'S AND USER'S OWN WORDS ("here are three options", "I really need
this now"), which is not present in a tool-call-only extraction. This script
instead vendors the conversation grain: one JSON line per simulation, carrying
the assistant/user message text plus a flattened tool-call-name trail for the
claims (A4, A6) that need only the trail, not the text.

Source: tau2-bench's own committed 4-trial airline results (public,
https://github.com/sierra-research/tau2-bench,
``data/tau2/results/final/<model>_airline_*_4trials.json``). Unlike the
tool-call-only vendoring above (trial 0 only, one file per model), this script
takes ALL FOUR TRIALS from a single model file -- 50 tasks x 4 trials = 200
simulations -- because the airline-engagement-pack task explicitly measures
over "the 200-sim airline file". Default model: claude-3-7-sonnet (the model
already vendored for the tool-call-only reference, so both datasets describe
the same underlying agent).

Dropped per-message fields: ``cost``, ``usage``, ``raw_data``, ``timestamp``,
``turn_idx`` -- session-accounting and replay-internal fields the pack's text
predicates never read; keeping them would triple output size for no claim this
pack computes. ``role: tool`` messages (raw tool result payloads) are dropped
entirely -- the pack's claims either read assistant/user prose or the
tool-call NAME trail, never a tool result body.

Run: ``python scripts/vendor_tau2_airline_conversations.py
--tau2-results-dir <path to tau2-bench's data/tau2/results/final>``
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "capsule_ledger" / "examples" / "data" / "tau2_airline"

MODEL_FILES = {
    "claude-3-7-sonnet": "claude-3-7-sonnet-20250219_airline_default_gpt-4.1-2025-04-14_4trials.json",
}


def _messages_for_sim(sim: dict) -> list[dict]:
    out = []
    for m in sim["messages"]:
        role = m.get("role")
        if role in ("assistant", "user"):
            content = m.get("content")
            record: dict = {"role": role, "content": content if isinstance(content, str) else ""}
            tool_call_names = [tc["name"] for tc in (m.get("tool_calls") or [])]
            if tool_call_names:
                record["tool_call_names"] = tool_call_names
            out.append(record)
    return out


def _write_dataset(sims: list[dict], out_path: Path) -> tuple[int, int]:
    n_sims = 0
    n_messages = 0
    with open(out_path, "w", encoding="utf-8") as fh:
        for sim in sims:
            messages = _messages_for_sim(sim)
            record = {
                "sim_id": sim["id"],
                "task_id": sim["task_id"],
                "trial": sim["trial"],
                "termination_reason": sim.get("termination_reason"),
                "messages": messages,
            }
            fh.write(json.dumps(record, separators=(",", ":")) + "\n")
            n_sims += 1
            n_messages += len(messages)
    return n_sims, n_messages


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tau2-results-dir", required=True, help="tau2-bench's data/tau2/results/final directory")
    parser.add_argument("--model", default="claude-3-7-sonnet", choices=sorted(MODEL_FILES))
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    args = parser.parse_args()

    results_dir = Path(args.tau2_results_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    fname = MODEL_FILES[args.model]
    src = results_dir / fname
    d = json.loads(src.read_text())
    sims = sorted(d["simulations"], key=lambda s: (int(s["task_id"]), s["trial"]))
    out_path = out_dir / f"tau2_conversations_{args.model}_airline_4trials.jsonl"
    n_sims, n_messages = _write_dataset(sims, out_path)

    entry = {
        "source_repo": "https://github.com/sierra-research/tau2-bench",
        "source_file": f"data/tau2/results/final/{fname}",
        "source_git_commit": d["info"].get("git_commit"),
        "trials_used": "all (0-3)",
        "num_simulations": n_sims,
        "num_messages": n_messages,
        "output_file": out_path.name,
        "output_bytes": out_path.stat().st_size,
        "note": (
            "conversation-grain companion to tau2_committed_<model>_airline_trial0.jsonl -- "
            "assistant/user message text + tool-call-name trail, for "
            "[ldg-airline-engagement-pack]'s text-reading claims (A1/A3/A5/A7)"
        ),
    }
    print(f"{args.model}: {n_sims} simulations, {n_messages} messages -> {out_path}")

    provenance_path = out_dir / "PROVENANCE.json"
    provenance = json.loads(provenance_path.read_text()) if provenance_path.exists() else {}
    provenance[f"conversations-{args.model}"] = entry
    provenance_path.write_text(json.dumps(provenance, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
