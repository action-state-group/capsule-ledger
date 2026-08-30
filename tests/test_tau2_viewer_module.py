# SPDX-License-Identifier: Apache-2.0
"""The base-viewer plug-in seam + the tau2 / conversation_exchange domain
module.

Three things, matching the deliverable:

* **the seam registers + dispatches** -- the base's JS ``CapsuleViewer.register``
  gets a ``conversation_exchange`` renderer and ``boot()`` dispatches each record
  to it keyed on ``asg_payload.event`` (proved in-browser via the node harness);
* **the tau2 module renders the fields** -- friendly model, the
  ``generated with: temperature 0, seed …`` line, the ``in / out / total`` token
  split, and the honest ``API-served`` marker all land in the rendered card;
* **a forged co-carried value is re-derived** -- the base recomputes the
  co-carried record's ``capsule_id`` in-browser, so a tampered token count yields
  a MISMATCH rather than being trusted.

The Python side also checks the seam wiring directly (registration order, the
one-shell-slot embed invariant) so the seam is covered even where ``node`` is
unavailable.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from capsule_ledger.bundle_viewer import base_viewer as bv
from capsule_ledger.bundle_viewer import (
    build_entry,
    build_payload,
    encode_fragment,
    render_base_viewer_html,
)
from capsule_ledger.examples.airline_engagement_pack import DEVELOPER, OPERATOR, load_conversations
from capsule_ledger.examples.tau2_conversation_exchange import seal_tau2_sim_exchange

HARNESS = Path(__file__).parent / "js_harness_base_viewer_seam.mjs"

FRIENDLY = "Claude-3.7-Sonnet"


def _disclosed_conversation(sim: dict) -> dict:
    messages = []
    for m in sim["messages"]:
        turn = {"role": m["role"], "content": m.get("content", "")}
        if m.get("tool_call_names"):
            turn["tool_call_names"] = list(m["tool_call_names"])
        messages.append(turn)
    return {"disclosed": True, "messages": messages}


def _sims_with_tools(n: int) -> list[dict]:
    sims = load_conversations()
    chosen = [s for s in sims if any(m.get("tool_call_names") for m in s["messages"])][:n]
    assert len(chosen) == n, "need enriched sims with tool calls for the demo"
    return chosen


@pytest.fixture
def sealed_entries(signer):
    sims = _sims_with_tools(4)
    entries = []
    for sim in sims:
        cap = seal_tau2_sim_exchange(sim, operator=OPERATOR, developer=DEVELOPER, signer=signer)
        entries.append(build_entry(cap, conversation=_disclosed_conversation(sim)))
    return sims, entries


# --------------------------------------------------------------------------
# The seam, checked directly in Python.
# --------------------------------------------------------------------------


def test_seam_wires_base_then_modules_and_one_embed_slot(sealed_entries):
    """The base inlines its own script FIRST (the modules call
    ``register`` on load), then every registered domain module, and embeds the
    fragment in exactly one slot -- the load-bearing seam + fragment-carry
    invariants."""
    # the conversation_exchange module is registered on the seam.
    assert "conversation_exchange_card.js" in bv.MODULE_SCRIPTS

    _, entries = sealed_entries
    fragment = encode_fragment(build_payload(entries, operator=OPERATOR))
    html = render_base_viewer_html(fragment)

    # base script appears before the module script (register-after-base order):
    # the base exposes window.CapsuleViewer, then the module's throw-guard checks
    # for it on load -- so the base's export must precede the module's guard.
    base_export = html.index("window.CapsuleViewer = CapsuleViewer")
    module_guard = html.index("base CapsuleViewer not loaded")
    assert base_export < module_guard
    # the module registers on the base -- its registration call is present.
    assert html.rindex('CapsuleViewer.register("conversation_exchange"') > base_export

    # exactly one fragment embed slot; the fragment never leaks into a boot guard.
    assert html.count("window.__CAPSULE_FRAGMENT_B64U__=") == 1
    assert f'!== "{fragment}"' not in html
    # self-contained: no external script.
    assert "<script src" not in html


def test_base_owns_recompute_module_carries_no_digest_port():
    """The domain module must not fork the base's canonicalization -- the seam
    exists precisely so the card renderer never re-implements the digest. Assert
    the module source carries no JCS/SHA porting, only a render + register."""
    static = Path(bv.__file__).parent / "static"
    module = (static / "conversation_exchange_card.js").read_text(encoding="utf-8")
    base = (static / "capsule_viewer.js").read_text(encoding="utf-8")
    # the base owns these; the module must not.
    for forked in ("crypto.subtle", "function jcsValue", "sha256Hex", "function recomputeCapsuleId"):
        assert forked in base, f"base must own {forked}"
        assert forked not in module, f"module must NOT fork {forked} -- route through the seam"
    # the module DOES register on the seam.
    assert 'CapsuleViewer.register("conversation_exchange"' in module


def test_conversation_disclosure_is_separate_from_the_sealed_capsule(sealed_entries):
    """The readable transcript rides as an operator DISCLOSURE in the fragment;
    the sealed capsule itself carries only digests, never the raw text."""
    sims, entries = sealed_entries
    entry = entries[0]
    # the sealed record holds no raw message content.
    blob = json.dumps(entry["record"])
    for msg in sims[0]["messages"]:
        content = msg.get("content")
        if content and content.strip():
            assert content not in blob
    # the disclosure block DOES carry the readable turns for the card.
    assert entry["conversation"]["disclosed"] is True
    assert entry["conversation"]["messages"][0]["content"]


# --------------------------------------------------------------------------
# The in-browser proof: seam dispatch + module fields + forgery re-derivation.
# --------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_seam_dispatch_and_module_render_and_forgery_in_browser(sealed_entries, tmp_path):
    sims, entries = sealed_entries
    fragment = encode_fragment(build_payload(entries, operator=OPERATOR, source="tau2 demo"))
    html = render_base_viewer_html(fragment)
    html_path = tmp_path / "tau2-viewer.html"
    html_path.write_text(html, encoding="utf-8")

    sample = entries[0]["record"]
    expect = {
        "n_entries": len(entries),
        "friendly_model": FRIENDLY,
        "gen_params_line": "generated with: temperature 0, seed "
        + str(sample["model_attestation"]["compute_attestation"]["generation_parameters"]["seed"]),
        "usage_line": (
            f'{sample["model_attestation"]["compute_attestation"]["usage"]["prompt_tokens"]} in / '
            f'{sample["model_attestation"]["compute_attestation"]["usage"]["completion_tokens"]} out / '
            f'{sample["model_attestation"]["compute_attestation"]["usage"]["total_tokens"]} total'
        ),
        "api_marker": "API-served",
        "tool_call_name": next(
            m["tool_call_names"][0] for m in sims[0]["messages"] if m.get("tool_call_names")
        ),
        "sample_record": sample,
    }
    expect_path = tmp_path / "expect.json"
    expect_path.write_text(json.dumps(expect), encoding="utf-8")

    result = subprocess.run(
        ["node", str(HARNESS), str(html_path), str(expect_path)],
        capture_output=True,
        text=True,
    )
    report = result.stdout + "\n" + result.stderr
    assert result.returncode == 0, report
    parsed = json.loads(result.stdout)
    assert parsed["fail"] == [], parsed
    # the three named deliverables are among the passes.
    passes = " | ".join(parsed["pass"])
    assert "conversation_exchange renderer registered" in passes
    assert "in/out token split" in passes
    assert "re-derives a DIFFERENT capsule_id" in passes
