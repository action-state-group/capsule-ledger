# SPDX-License-Identifier: Apache-2.0
"""The policy manifest: one canonical, digestible file listing the active
fold and wicket (guard-constraint) definitions, *by digest*.

This is the declare-attest-verify piece (in-toto/SLSA pattern) for guard
policy: a manifest is a lockfile, not a copy. Each entry cites a fold_id or
wicket_id plus that definition's own already-real ``definition_digest()``
(``folds/definition.py`` / ``guards/wickets/definition.py``) -- never the
definition body itself, mirroring the same "definitions-by-digest, never
definitions-by-copy" rule fold *results* already follow when they cite
``fold_digest`` on a ledger record rather than embedding the fold. Because a
manifest is itself just declarative data, it gets a digest the exact same
way: SHA-256 over the JCS-canonical bytes of its own canonical form (see
``manifest_digest()``), via the same ``agent_action_capsule.canonical.
json_digest`` every other digest in this codebase uses.

Whether a manifest's pinned digests actually match what's sitting in the
fold/wicket catalogs *right now* is not this module's job -- see
``resolve.py`` for that cross-check. This module only parses and digests the
manifest as declared.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from agent_action_capsule.canonical import json_digest
from agent_action_capsule.contracts import is_hex64

from .errors import (
    DUPLICATE_FOLD_REF,
    DUPLICATE_WICKET_REF,
    INVALID_DIGEST,
    INVALID_MANIFEST_ID,
    MALFORMED_MANIFEST,
    PolicyManifestError,
)

__all__ = ["MANIFEST_ID_RE", "FoldRef", "WicketRef", "Manifest", "parse_manifest"]

# manifest_id: same "human name + semver" shape as fold_id/wicket_id.
MANIFEST_ID_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*/\d+\.\d+\.\d+$")


@dataclass(frozen=True)
class FoldRef:
    fold_id: str
    digest: str


@dataclass(frozen=True)
class WicketRef:
    wicket_id: str
    digest: str


@dataclass(frozen=True)
class Manifest:
    manifest_id: str
    folds: tuple[FoldRef, ...] = ()
    wickets: tuple[WicketRef, ...] = ()

    def canonical_dict(self) -> dict:
        """The JCS-canonicalizable form of this manifest -- drives manifest_digest().

        List order is preserved (not sorted) and is part of what gets
        digested, same as a fold definition's ``reads`` list -- editing the
        manifest file (even just reordering entries) is a manifest change."""
        return {
            "manifest_id": self.manifest_id,
            "folds": [{"fold_id": f.fold_id, "digest": f.digest} for f in self.folds],
            "wickets": [{"wicket_id": w.wicket_id, "digest": w.digest} for w in self.wickets],
        }

    def manifest_digest(self) -> str:
        """SHA-256 over the JCS bytes of the canonical manifest.

        Every field in ``canonical_dict()`` is a string (ids and hex
        digests), so unlike ``FoldDefinition.definition_digest()`` there is
        no float/unsafe-integer failure mode to guard here -- ``json_digest``
        cannot raise on an all-string payload."""
        return json_digest(self.canonical_dict())


def _check_digest(value: Any, context: str) -> str:
    if not isinstance(value, str) or not is_hex64(value):
        raise PolicyManifestError(INVALID_DIGEST, f"{context} must be a 64-hex-char digest string, got {value!r}")
    return value


def parse_manifest(data: Any) -> Manifest:
    """Validate a plain dict (as loaded from YAML) into a ``Manifest``."""
    if not isinstance(data, dict):
        raise PolicyManifestError(MALFORMED_MANIFEST, "manifest must be a mapping")

    manifest_id = data.get("manifest_id")
    if not isinstance(manifest_id, str) or not MANIFEST_ID_RE.match(manifest_id):
        raise PolicyManifestError(
            INVALID_MANIFEST_ID,
            f"manifest_id {manifest_id!r} must match '<namespace>[.<namespace>...]/<major>.<minor>.<patch>' "
            "(e.g. 'default/1.0.0')",
        )

    raw_folds = data.get("folds") or []
    if not isinstance(raw_folds, list):
        raise PolicyManifestError(MALFORMED_MANIFEST, "folds must be a list")
    folds: list[FoldRef] = []
    seen_fold_ids: set[str] = set()
    for entry in raw_folds:
        if not isinstance(entry, dict) or "fold_id" not in entry or "digest" not in entry:
            raise PolicyManifestError(MALFORMED_MANIFEST, f"each folds entry needs 'fold_id' and 'digest': {entry!r}")
        fold_id = entry["fold_id"]
        if not isinstance(fold_id, str) or not fold_id:
            raise PolicyManifestError(MALFORMED_MANIFEST, f"folds[].fold_id must be a non-empty string: {entry!r}")
        if fold_id in seen_fold_ids:
            raise PolicyManifestError(DUPLICATE_FOLD_REF, f"fold_id {fold_id!r} declared more than once")
        seen_fold_ids.add(fold_id)
        digest = _check_digest(entry["digest"], f"folds[{fold_id!r}].digest")
        folds.append(FoldRef(fold_id=fold_id, digest=digest))

    raw_wickets = data.get("wickets") or []
    if not isinstance(raw_wickets, list):
        raise PolicyManifestError(MALFORMED_MANIFEST, "wickets must be a list")
    wickets: list[WicketRef] = []
    seen_wicket_ids: set[str] = set()
    for entry in raw_wickets:
        if not isinstance(entry, dict) or "wicket_id" not in entry or "digest" not in entry:
            raise PolicyManifestError(
                MALFORMED_MANIFEST, f"each wickets entry needs 'wicket_id' and 'digest': {entry!r}"
            )
        wicket_id = entry["wicket_id"]
        if not isinstance(wicket_id, str) or not wicket_id:
            raise PolicyManifestError(MALFORMED_MANIFEST, f"wickets[].wicket_id must be a non-empty string: {entry!r}")
        if wicket_id in seen_wicket_ids:
            raise PolicyManifestError(DUPLICATE_WICKET_REF, f"wicket_id {wicket_id!r} declared more than once")
        seen_wicket_ids.add(wicket_id)
        digest = _check_digest(entry["digest"], f"wickets[{wicket_id!r}].digest")
        wickets.append(WicketRef(wicket_id=wicket_id, digest=digest))

    return Manifest(manifest_id=manifest_id, folds=tuple(folds), wickets=tuple(wickets))
