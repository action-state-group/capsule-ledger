# SPDX-License-Identifier: Apache-2.0
"""OTLP/``gen_ai`` semantic-convention mapping -- PRIMARY export target.

**Isolation is the point of this file.** OTel's ``gen_ai.*`` conventions are
experimental, not stable: as of 2026-06-12 the entire ``gen_ai`` convention
set was deprecated out of the main ``open-telemetry/semantic-conventions``
repo into a dedicated ``open-telemetry/semantic-conventions-genai`` repo that
(as of this writing) has no tagged release -- attribute names are actively
moving. Every literal ``gen_ai.*`` string in this package lives in this one
file. If/when a name changes upstream, this is the only file that needs to
change; nothing outside ``otel_export`` ever imports a ``gen_ai.*`` constant
or spells one out itself. ``event.py``'s ``DecisionEvent.to_attributes()``
attribute names (``receipt.digest``, ``decision``, etc.) are this package's
own stable vocabulary and are unaffected by upstream churn either way.

``gen_ai`` covers LLM/tool-call telemetry -- model, tokens, tool name,
agent/conversation identity. It has **nothing** for tamper-evidence,
signing, or non-repudiation, so the receipt/manifest/plan/containment
attributes ride alongside the ``gen_ai.*`` ones in the same attribute dict
under this package's own namespace; there is no ``gen_ai`` field to fold
them into and manufacturing one would be worse than leaving them separate.
"""
from __future__ import annotations

from .event import DecisionEvent

__all__ = ["GENAI_OPERATION_NAME", "to_genai_attributes"]

# The closest existing gen_ai operation name for "an agent's proposed action
# was mediated" -- gen_ai has no operation for a governance/gating decision
# itself, only for the tool call the decision gates.
GENAI_OPERATION_NAME = "execute_tool"


def to_genai_attributes(event: DecisionEvent) -> dict[str, str | int]:
    """This package's own attribute set, plus the ``gen_ai.*`` attributes
    that have a genuine counterpart. Fields with no ``gen_ai`` equivalent
    (``decision``, ``receipt.digest``, ``manifest.digest``, ``plan.digest``,
    ``containment.result``) are carried only under this package's own
    namespace -- see module docstring."""
    attrs = event.to_attributes()
    attrs["gen_ai.operation.name"] = GENAI_OPERATION_NAME
    attrs["gen_ai.tool.name"] = event.action_verb
    if event.identity_agent is not None:
        attrs["gen_ai.agent.id"] = event.identity_agent
    if event.identity_session is not None:
        attrs["gen_ai.conversation.id"] = event.identity_session
    return attrs
