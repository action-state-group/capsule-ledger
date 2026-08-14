# SPDX-License-Identifier: Apache-2.0
"""Drift guard for the vendored offline bundle-viewer shell.

``scripts/vendor_bundle_viewer.py`` is an unguarded manual step -- its own
docstring says "re-run this script by hand whenever scitt-cose's bundle
viewer changes." That is exactly how the vendored copy went seven commits
stale, silently shipping a viewer without the Sequence tamper-check fix
(scitt-cose PR #26) in every ``--with-viewer`` bundle. This test is the
guard: when a local scitt-cose checkout is available, it fails loudly if
the vendored file's recorded provenance commit is not that checkout's
current HEAD -- the same optional-sibling-checkout convention
``test_bundle_e2e_capsule_ledger.py`` (the scitt-cose side of this pair)
already uses for ``CAPSULE_LEDGER_PATH``.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VENDORED_PATH = REPO_ROOT / "capsule_ledger" / "bundle_viewer" / "static" / "offline_shell.html"

_PROVENANCE_RE = re.compile(r"render_bundle_page\(offline=True\), commit ([0-9a-f]{40})\.")


def _vendored_commit() -> str:
    header = VENDORED_PATH.read_text(encoding="utf-8")[:2000]
    m = _PROVENANCE_RE.search(header)
    assert m, (
        f"{VENDORED_PATH} has no parseable provenance header -- expected a line matching "
        f"{_PROVENANCE_RE.pattern!r} in the first 2000 bytes. Was the file hand-edited?"
    )
    return m.group(1)


def _find_scitt_cose() -> Path | None:
    candidates = []
    env = os.environ.get("SCITT_COSE_PATH")
    if env:
        candidates.append(Path(env))
    candidates.append(REPO_ROOT.parent / "scitt-cose")
    for c in candidates:
        if c and (c / "hosted_profiles" / "hosted.py").exists():
            return c.resolve()
    return None


def test_vendored_provenance_header_is_parseable():
    """Always runs, no sibling checkout needed -- catches a hand-edited or
    malformed header even when there is nothing to compare it against."""
    commit = _vendored_commit()
    assert len(commit) == 40


def test_vendored_shell_matches_current_scitt_cose_main():
    """The real drift check. Skips (does not silently pass) when no sibling
    scitt-cose checkout is available -- same shape as the e2e test on the
    other side of this pair."""
    scitt_cose = _find_scitt_cose()
    if scitt_cose is None:
        import pytest

        pytest.skip(
            "no scitt-cose checkout found ($SCITT_COSE_PATH or ../scitt-cose) -- "
            "drift cannot be checked without one"
        )

    current_head = subprocess.run(
        ["git", "-C", str(scitt_cose), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    vendored_commit = _vendored_commit()

    assert vendored_commit == current_head, (
        f"vendored offline_shell.html was generated from scitt-cose@{vendored_commit[:12]}, "
        f"but the checkout at {scitt_cose} is now at {current_head[:12]} -- re-run "
        f"'python scripts/vendor_bundle_viewer.py {scitt_cose}' to pick up the drift "
        f"before it ships in another --with-viewer bundle."
    )
