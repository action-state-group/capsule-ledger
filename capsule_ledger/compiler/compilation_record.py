# SPDX-License-Identifier: Apache-2.0
"""The compilation record C (design §2.1) -- the load-bearing property of
the whole compiler: ``D -> P + F + C sealed``, where
``C = {D_digest, P_digest, F_digest, compiler_id, compiler_version,
D_prev_digest, replay_report_digest}``.

C exists to make forward/backward drift DETECTABLE: a system that blocks
one thing (``P``) and reports another (``F``), both honestly, because the
two halves were authored separately and diverged. A receipt carrying ``P``
without ``C`` cannot tell a relying party whether the report describes the
rule that was actually enforced. C is a sealed capsule, not a file, so its
own provenance is checkable rather than asserted -- same as every other
record this codebase produces.

``D_prev_digest`` and ``replay_report_digest`` make declarations a
LINEAGE: each accepted declaration chains to the one it replaced, and pins
the replay report (design §3.5, "what would this change have held") that
justified the change. Building this capsule is not publishing it -- G-IP1
(build plan gate table) gates lifting §2-§4 of the design doc into public
docs, never this code.
"""
from __future__ import annotations

from agent_action_capsule.contracts import is_hex64

from ..guards.capsule import build_event_capsule
from ..guards.signing import Signer

__all__ = ["EVENT_COMPILATION_RECORD", "build_compilation_record_capsule"]

EVENT_COMPILATION_RECORD = "compiler.compilation_record"

_REQUIRED_DIGESTS = ("d_digest", "p_digest", "f_digest")
_OPTIONAL_DIGESTS = ("d_prev_digest", "replay_report_digest")


def build_compilation_record_capsule(
    *,
    d_digest: str,
    p_digest: str,
    f_digest: str,
    compiler_id: str,
    compiler_version: str,
    operator: str,
    developer: str,
    signer: Signer,
    d_prev_digest: str | None = None,
    replay_report_digest: str | None = None,
    timestamp: str | None = None,
    action_id: str | None = None,
) -> dict:
    """Seal ``C``. ``d_digest``/``p_digest``/``f_digest`` are required --
    there is no such thing as a compilation record for a plan or fold that
    was never compiled. ``d_prev_digest``/``replay_report_digest`` are
    omitted (not null) when this is the declaration's first acceptance, so
    an absent lineage link stays indistinguishable from "genesis" rather
    than a null that could be mistaken for "checked and empty"."""
    digests = {
        "d_digest": d_digest,
        "p_digest": p_digest,
        "f_digest": f_digest,
        "d_prev_digest": d_prev_digest,
        "replay_report_digest": replay_report_digest,
    }
    for name in _REQUIRED_DIGESTS:
        value = digests[name]
        if not is_hex64(value):
            raise ValueError(f"{name} must be a 64-hex SHA-256 digest; got {value!r}")
    for name in _OPTIONAL_DIGESTS:
        value = digests[name]
        if value is not None and not is_hex64(value):
            raise ValueError(f"{name} must be a 64-hex SHA-256 digest or None; got {value!r}")
    if not compiler_id:
        raise ValueError("compiler_id is required")
    if not compiler_version:
        raise ValueError("compiler_version is required")

    detail: dict = {
        "d_digest": d_digest,
        "p_digest": p_digest,
        "f_digest": f_digest,
        "compiler_id": compiler_id,
        "compiler_version": compiler_version,
    }
    if d_prev_digest is not None:
        detail["d_prev_digest"] = d_prev_digest
    if replay_report_digest is not None:
        detail["replay_report_digest"] = replay_report_digest

    return build_event_capsule(
        operator=operator,
        developer=developer,
        signer=signer,
        event=EVENT_COMPILATION_RECORD,
        detail=detail,
        timestamp=timestamp,
        action_id=action_id or f"compiler.compilation_record/{d_digest}",
    )
