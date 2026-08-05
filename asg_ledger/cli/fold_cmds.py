# SPDX-License-Identifier: Apache-2.0
"""`asg fold` verbs: hot-load a catalog directory, lint a definition, replay
one over a fixture ledger (T1's stub, moved here unchanged so `main.py`
stays a thin dispatcher; see that module's original docstring for why this
lives in `cli/` at all)."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

DEFAULT_CATALOG_DIR = Path(__file__).resolve().parent.parent / "folds" / "catalog_defs"

__all__ = ["add_parser"]


def _catalog_dir(args: argparse.Namespace) -> Path:
    if getattr(args, "dir", None):
        return Path(args.dir)
    env = os.environ.get("ASG_FOLD_DIR")
    if env:
        return Path(env)
    return DEFAULT_CATALOG_DIR


def _cmd_fold_list(args: argparse.Namespace) -> int:
    from ..folds import Catalog

    catalog = Catalog(_catalog_dir(args))
    for entry in catalog.list_entries():
        print(f"{entry.definition.fold_id}\t{entry.digest}\t{entry.source_path}")
    errors = catalog.list_errors()
    for err in errors:
        print(f"ERROR {err.source_path}: {err.reason}: {err.message}", file=sys.stderr)
    return 1 if errors else 0


def _cmd_fold_lint(args: argparse.Namespace) -> int:
    from ..folds.errors import FoldDefinitionError
    from ..folds.loader import load_definition_file

    try:
        definition = load_definition_file(args.path)
        digest = definition.definition_digest()
    except FoldDefinitionError as exc:
        print(f"FAIL {exc.reason}: {exc}", file=sys.stderr)
        return 1
    print(f"ok  {definition.fold_id}  {digest}")
    return 0


def _cmd_fold_new(args: argparse.Namespace) -> int:
    template = f"""fold_id: {args.fold_id}
reads:
  - path: developer
    erasure_class: commitment-ok
key: developer
reduce:
  reducer: count
emit: count
"""
    out_dir = _catalog_dir(args)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / (args.fold_id.split("/")[0] + ".yaml")
    if out_path.exists() and not args.force:
        print(f"refusing to overwrite existing {out_path} (use --force)", file=sys.stderr)
        return 1
    out_path.write_text(template)
    print(f"wrote {out_path}")
    return 0


def _cmd_fold_test(args: argparse.Namespace) -> int:
    from ..folds import Catalog
    from ..folds.engine import evaluate_one
    from ..folds.errors import FoldDefinitionError, FoldDeterminismError
    from ..folds.loader import load_definition_file

    path = Path(args.fold)
    try:
        if path.exists():
            definition = load_definition_file(path)
        else:
            catalog = Catalog(_catalog_dir(args))
            entry = catalog.get(args.fold)
            if entry is None:
                print(f"no such fold {args.fold!r} in catalog {catalog.directory}", file=sys.stderr)
                return 1
            definition = entry.definition
    except FoldDefinitionError as exc:
        print(f"FAIL {exc.reason}: {exc}", file=sys.stderr)
        return 1

    records = []
    with open(args.ledger) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    try:
        trace = evaluate_one(definition, records, key_value=args.key, as_of=args.as_of)
    except FoldDeterminismError as exc:
        print(f"FAIL {exc.reason}: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(trace.to_envelope(), indent=2, sort_keys=True))
    return 0


def add_parser(sub: argparse._SubParsersAction) -> argparse.ArgumentParser:
    fold = sub.add_parser("fold", help="fold catalog: list, new, test, lint")
    fold_sub = fold.add_subparsers(dest="fold_command")
    fold.set_defaults(fold_parser=fold)

    p_list = fold_sub.add_parser("list", help="list catalog fold definitions")
    p_list.add_argument("--dir", help="catalog directory (default: built-in catalog, or $ASG_FOLD_DIR)")
    p_list.set_defaults(func=_cmd_fold_list)

    p_new = fold_sub.add_parser("new", help="write a fold-definition template into the catalog directory")
    p_new.add_argument("fold_id", help="e.g. spend.weekly/1.0.0")
    p_new.add_argument("--dir", help="catalog directory to write into")
    p_new.add_argument("--force", action="store_true", help="overwrite an existing file")
    p_new.set_defaults(func=_cmd_fold_new)

    p_lint = fold_sub.add_parser("lint", help="validate a fold-definition YAML file")
    p_lint.add_argument("path")
    p_lint.set_defaults(func=_cmd_fold_lint)

    p_test = fold_sub.add_parser("test", help="replay a fold over a fixture ledger and print its envelope")
    p_test.add_argument("fold", help="fold_id, definition_digest, or a path to a definition YAML file")
    p_test.add_argument("--ledger", required=True, help="path to a JSONL capsule ledger")
    p_test.add_argument("--dir", help="catalog directory (default: built-in catalog, or $ASG_FOLD_DIR)")
    p_test.add_argument("--key", default=None, help="group key value to evaluate (omit for key-less folds)")
    p_test.add_argument("--as-of", dest="as_of", default=None, help="reference timestamp for rolling windows")
    p_test.set_defaults(func=_cmd_fold_test)

    return fold
