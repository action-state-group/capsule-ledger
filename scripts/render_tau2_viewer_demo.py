#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Render a tau2 conversation-exchange demo over a handful of REAL vendored
tau2 airline sims, through the BASE viewer + the tau2/conversation_exchange
DOMAIN MODULE.

This is the composition the architecture requires, exercised end-to-end:

  1. Seal each sim as a ``conversation_exchange`` capsule
     (``seal_tau2_sim_exchange`` -> ``build_conversation_exchange_capsule``),
     carrying the real vendored ``generation_parameters``/``usage``/``served_by``.
  2. Attach the operator-disclosed readable transcript (the capsule itself
     holds only digests; the readable turns are a deliberate disclosure that
     rides in the fragment for the domain card to render words-first).
  3. Build ONE fragment payload and render it with ``render_base_viewer_html``
     -- the base owns fragment carry + in-browser recompute + the security
     toggle; the ``conversation_exchange`` module (registered on the seam)
     renders each card body.

The output is a single self-contained HTML file: open ``<file>#<fragment>``
(or just the file -- the fragment is also embedded) with no server.

Usage:
    python scripts/render_tau2_viewer_demo.py [OUT_HTML] [N_SIMS]
"""
from __future__ import annotations

import sys
from pathlib import Path

from capsule_ledger.bundle_viewer import (
    build_entry,
    build_payload,
    encode_fragment,
    render_base_viewer_html,
)
from capsule_ledger.examples.airline_engagement_pack import (
    DEVELOPER,
    OPERATOR,
    load_conversations,
)
from capsule_ledger.examples.tau2_conversation_exchange import seal_tau2_sim_exchange
from capsule_ledger.guards import LocalSigner


def _disclosed_conversation(sim: dict) -> dict:
    """The operator-disclosed readable transcript for the domain card: the
    assistant/user turns + the tool-call NAME trail, exactly as tau2 vendors
    them. This is a DISCLOSURE (the sealed capsule holds only digests)."""
    messages = []
    for m in sim["messages"]:
        turn = {"role": m["role"], "content": m.get("content", "")}
        names = m.get("tool_call_names")
        if names:
            turn["tool_call_names"] = list(names)
        messages.append(turn)
    return {"disclosed": True, "messages": messages}


def _pick_sims(sims: list[dict], n: int) -> list[dict]:
    """Prefer sims that exercise the tool-call trail (more interesting cards),
    falling back to the first sims if fewer carry tool calls."""
    with_tools = [s for s in sims if any(m.get("tool_call_names") for m in s["messages"])]
    chosen = with_tools[:n]
    if len(chosen) < n:
        for s in sims:
            if s not in chosen:
                chosen.append(s)
            if len(chosen) >= n:
                break
    return chosen[:n]


def render_demo(out_path: Path, n_sims: int = 4) -> str:
    sims = load_conversations()
    chosen = _pick_sims(sims, n_sims)
    # A deterministic local signer -- these are demo capsules over public tau2
    # data; the point is the viewer composition, not a production key.
    signer = LocalSigner(key_id="tau2-demo-key", secret=b"tau2-viewer-demo")

    entries = []
    for sim in chosen:
        capsule = seal_tau2_sim_exchange(sim, operator=OPERATOR, developer=DEVELOPER, signer=signer)
        entries.append(build_entry(capsule, conversation=_disclosed_conversation(sim)))

    payload = build_payload(
        entries,
        operator=OPERATOR,
        source="tau2-bench airline sims (claude-3-7-sonnet, real vendored transcripts)",
    )
    fragment = encode_fragment(payload)
    html = render_base_viewer_html(fragment)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return fragment


def main(argv: list[str]) -> int:
    out = Path(argv[1]) if len(argv) > 1 else Path("tau2-viewer.html")
    n = int(argv[2]) if len(argv) > 2 else 4
    fragment = render_demo(out, n)
    print(f"tau2 viewer demo: {n} capsule(s) via base + conversation_exchange module -> {out}")
    print(f"permalink: file://{out.resolve()}#{fragment}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
