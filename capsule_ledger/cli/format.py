# SPDX-License-Identifier: Apache-2.0
"""Shared CLI output discipline: the DM Mono fold-envelope line, staleness
copy, the CLI-echo canonical form, and one capsule-summary helper.

The envelope-line format is copied verbatim from the design handoff
README's "Product laws" section (`design_handoff_capsule_ledger_ux/README.md`):
``fold <id> · records N–M · checkpoint #X · as of <staleness>`` -- literal
text output, not a font choice. ``<id>`` is the fold's own ``fold`` envelope
field (the definition digest already computed by the fold engine), never a
name this module invents.
"""
from __future__ import annotations

import shlex

__all__ = [
    "format_staleness",
    "format_envelope_line",
    "build_echo",
    "summarize_action",
    "format_verdict",
    "format_verdict_label",
]


def format_staleness(age_ms: int) -> str:
    """Render a checkpoint age in the design's "as of 14s ago" style.

    ``age_ms <= 0`` (a value freshly computed by this same CLI invocation,
    never backdated) renders as "just now" rather than "0s ago".
    """
    if age_ms <= 0:
        return "just now"
    seconds = age_ms / 1000
    if seconds < 60:
        return f"{round(seconds)}s ago"
    minutes = seconds / 60
    if minutes < 60:
        return f"{round(minutes)}m ago"
    hours = minutes / 60
    if hours < 24:
        return f"{round(hours)}h ago"
    days = hours / 24
    return f"{round(days)}d ago"


def format_envelope_line(envelope: dict) -> str:
    """Render a fold result envelope (spec §4 shape) as the literal DM Mono line."""
    r0, r1 = envelope["range"]
    checkpoint_num = envelope["checkpoint"].get("tree_size")
    staleness_ms = envelope["staleness"].get("checkpoint_age_ms", 0)
    return (
        f"fold {envelope['fold']} · records {r0}–{r1} · "
        f"checkpoint #{checkpoint_num} · as of {format_staleness(staleness_ms)}"
    )


def build_echo(verb: str, *, positional: str | None = None, flags: list[tuple[str, object]] = ()) -> str:
    """The CLI-echo canonical form: the exact, copy-pasteable invocation that
    produced this output (design handoff README, "CLI echo standing rule").
    Flag order is fixed (whatever the caller passes), not the order the user
    typed them in, so the same query always echoes identically.
    """
    tokens = ["capsule", verb]
    if positional is not None:
        tokens.append(shlex.quote(str(positional)))
    for flag, value in flags:
        if value is None or value is False:
            continue
        tokens.append(flag)
        if value is not True:
            tokens.append(shlex.quote(str(value)))
    return "≡ " + " ".join(tokens)


def format_verdict(disposition: dict) -> str:
    """Render ``disposition.verdict_class`` for a single-record "Verdict:"
    line, falling back to the gate ``decision`` it stands in for when
    ``verdict_class`` is legitimately absent (an allow asserts the gate's
    decision, never an execution outcome -- see ``guards/capsule.py``'s
    module docstring). Absent must never read as missing/broken data."""
    verdict_class = disposition.get("verdict_class")
    if verdict_class:
        return verdict_class
    decision = disposition.get("decision") or "(none)"
    return f"— (gate decision: {decision}; no effect claimed)"


def format_verdict_label(disposition: dict) -> str:
    """Compact form of ``format_verdict`` for tabular/breakdown display
    (verdict-distribution counts, per-record diff rows) where the full
    sentence would overflow a fixed-width column."""
    verdict_class = disposition.get("verdict_class")
    if verdict_class:
        return verdict_class
    decision = disposition.get("decision") or "(none)"
    return f"(gate decision: {decision})"


def summarize_action(capsule: dict) -> str:
    """The verb portion of ``action_id`` (e.g. "approve_purchase"), falling
    back to ``action_type`` for records with no ``action_id``."""
    action_id = capsule.get("action_id") or ""
    verb = action_id.split("/", 1)[0] if action_id else ""
    return verb or capsule.get("action_type") or "(unnamed action)"
