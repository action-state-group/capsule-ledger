# SPDX-License-Identifier: Apache-2.0
"""``[pack-propose-generic]``: run the generic "would this pack work" report
against any pack directory and any real corpus fixture -- what Steven runs
by hand, e.g. against ``standard-vendor`` after a prospect edits a copy of
it, or against the tau2-airline fixture to see the SAME kind of report the
airline-specific ``compile.py`` flow already produced, but for a pack that
has no hand-authored translator at all.

``--entity-key`` picks the field this run's Stage-1b repeat-traffic check
groups by -- REQUIRED, no default (see ``packs/measurability_report.py``'s
own docstring for why guessing one would be dishonest). For the tau2-airline
corpus, ``session_id`` is a real per-conversation field, but every
conversation there IS its own customer -- so passing ``session_id`` here
will correctly report every ``fold_counterparty``/``fold_cohort`` row as
"can't be shown", which is the honest finding for this corpus, not a bug in
this script.

Reads a corpus already vendored in tau2-``Results.save()`` shape
(``{"messages": [...]}}`` per unit) from a JSONL file -- NOT the sealed
ledger corpus (a different shape entirely; this report works over the
same kind of flat conversation-unit corpus ``corpus_verify.py`` already
expects, not a capsule ledger).

    $ PYTHONPATH=~/dev/asg/capsule-ledger python3 -m \\
          capsule_ledger.examples.pack_measurability_report \\
          --pack-dir capsule_ledger/packs/catalog/standard-vendor \\
          --corpus path/to/units.jsonl \\
          --entity-key session_id

$0, no model calls, no network -- this is a pure local report.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..packs.loader import load_pack_dir
from ..packs.measurability_report import build_measurability_report, render_terminal

__all__ = ["main"]

# The only entity-key choices this script knows how to resolve from a plain
# JSONL unit dict without guessing a pack-specific shape -- an explicit,
# closed set rather than an arbitrary Python-expression flag (no eval()).
_ENTITY_KEY_FIELDS = ("session_id", "developer", "operator")


def _load_corpus(path: Path) -> list[dict]:
    units = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                units.append(json.loads(line))
    return units


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pack-dir", required=True, help="directory containing pack.yaml (e.g. capsule_ledger/packs/catalog/standard-vendor)")
    parser.add_argument("--corpus", required=True, help="path to a JSONL file of units, each shaped {'messages': [...]}")
    parser.add_argument(
        "--entity-key", required=True, choices=_ENTITY_KEY_FIELDS,
        help="which field identifies a repeat entity for the Stage-1b fold_counterparty/fold_cohort check "
        "(required, no default -- see this module's own docstring for why)",
    )
    args = parser.parse_args(argv)

    pack = load_pack_dir(Path(args.pack_dir))
    units = _load_corpus(Path(args.corpus))
    key = args.entity_key

    report = build_measurability_report(pack, units, entity_key=lambda u, key=key: str(u.get(key)))
    print(f"pack: {pack.pack_id}")
    print(f"corpus: {args.corpus} ({len(units)} unit(s))")
    print(f"entity_key: {key}")
    print()
    print(render_terminal(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
