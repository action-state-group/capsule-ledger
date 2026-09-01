# SPDX-License-Identifier: Apache-2.0
"""The policy manifest: declares which fold and wicket definitions govern
guard decisions, by digest -- the declare-attest-verify piece for guard
policy (in-toto/SLSA pattern).

The manifest model, loader, and resolver survive here -- they're a
transitive dependency of holds/policy.py's ``resolve_hold_policy`` (core)
and of the shared test fixtures (``tests/conftest.py``) that build a
``ResolvedManifest`` for holds/guard tests. Manifest-activation-recording
(writing a ``policy_manifest_activated`` capsule to the ledger) is
bucket-code that moved to capsule-engine."""
from .errors import PolicyManifestError
from .loader import load_manifest_file, load_manifest_text
from .manifest import FoldRef, Manifest, PackRef, WicketRef, parse_manifest
from .resolve import ResolvedManifest, resolve_manifest

__all__ = [
    "Manifest",
    "FoldRef",
    "WicketRef",
    "PackRef",
    "parse_manifest",
    "load_manifest_text",
    "load_manifest_file",
    "PolicyManifestError",
    "ResolvedManifest",
    "resolve_manifest",
]
