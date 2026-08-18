# SPDX-License-Identifier: Apache-2.0
"""Re-vendor the offline bundle-viewer shell from a local scitt-cose checkout.

``capsule bundle --with-viewer`` (see ``capsule_ledger/bundle_viewer/``) embeds
a self-contained copy of scitt-cose's recipient viewer so a handed-over folder
verifies on a machine with no network at all. scitt-cose's ``hosted_profiles/``
package is deliberately excluded from the published ``scitt-cose`` wheel (see
its ``pyproject.toml``) -- it exists only in a full repo checkout, so there is
no pip dependency that would keep this in sync automatically. Instead we vendor
one generated artifact, ``capsule_ledger/bundle_viewer/static/offline_shell.html``,
and re-run this script by hand whenever scitt-cose's bundle viewer changes.

Both repos are Apache-2.0 (Action State Group), so vendoring a generated
artifact is not a licensing concern -- this script and the vendored file each
carry their own SPDX header, and the vendored file's header records the exact
scitt-cose commit it came from for provenance.

Usage:
    python scripts/vendor_bundle_viewer.py [path-to-scitt-cose-checkout]

If no path is given, tries the sibling-checkout convention this workspace
already uses elsewhere (``$SCITT_COSE_PATH``, else ``../scitt-cose`` relative
to this repo's root).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VENDORED_PATH = REPO_ROOT / "capsule_ledger" / "bundle_viewer" / "static" / "offline_shell.html"

PLACEHOLDER_TOKEN = "@@BUNDLE_FRAGMENT@@"


def _find_scitt_cose(explicit: str | None) -> Path:
    import os

    candidates = [Path(explicit)] if explicit else []
    env = os.environ.get("SCITT_COSE_PATH")
    if env:
        candidates.append(Path(env))
    candidates.append(REPO_ROOT.parent / "scitt-cose")
    for c in candidates:
        if c and (c / "hosted_profiles" / "hosted.py").exists():
            return c.resolve()
    raise SystemExit(
        "no scitt-cose checkout found -- pass a path, set $SCITT_COSE_PATH, "
        "or place a checkout at ../scitt-cose next to this repo"
    )


def main(argv: list[str]) -> int:
    scitt_cose = _find_scitt_cose(argv[1] if len(argv) > 1 else None)

    commit = subprocess.run(
        ["git", "-C", str(scitt_cose), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(scitt_cose), "status", "--porcelain"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    if dirty:
        raise SystemExit(
            f"refusing to vendor from a dirty scitt-cose checkout ({scitt_cose}) -- "
            "commit or stash first so the recorded commit sha is meaningful"
        )

    sys.path.insert(0, str(scitt_cose))
    from hosted_profiles.hosted import render_bundle_page  # noqa: PLC0415

    html = render_bundle_page(offline=True)
    if PLACEHOLDER_TOKEN not in html:
        raise SystemExit(
            f"vendored shell no longer contains the expected placeholder token "
            f"{PLACEHOLDER_TOKEN!r} -- scitt-cose's mechanism may have changed; "
            "update capsule_ledger/bundle_viewer/viewer.py to match before vendoring"
        )

    header = (
        "<!--\n"
        "  Vendored from action-state-group/scitt-cose, hosted_profiles/hosted.py,\n"
        f"  render_bundle_page(offline=True), commit {commit}.\n"
        "  Apache-2.0, same license as this repo. Do not hand-edit -- re-run\n"
        "  scripts/vendor_bundle_viewer.py against a scitt-cose checkout instead.\n"
        "  The one inline <script> tag right after <body> that sets the page's\n"
        "  bundle-fragment global is the real embed slot, swapped in at\n"
        "  bundle-creation time by capsule_ledger/bundle_viewer/viewer.py with the\n"
        "  real bundle fragment. Other appearances of that same placeholder text\n"
        "  further down are BUNDLE_JS's own placeholder-detection/re-splice logic\n"
        "  (the download button) -- do not touch those when substituting.\n"
        "-->\n"
    )
    VENDORED_PATH.parent.mkdir(parents=True, exist_ok=True)
    VENDORED_PATH.write_text(header + html, encoding="utf-8")
    print(f"wrote {VENDORED_PATH} (vendored from scitt-cose@{commit[:12]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
