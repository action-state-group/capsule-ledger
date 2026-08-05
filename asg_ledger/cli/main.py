"""`asg` CLI entry point.

Verb surface (log/show/verify/bundle/...) lands in a later task. This module
carries only the `fold` stub needed for T1: hot-load a catalog directory,
lint a definition, and replay one over a fixture ledger — enough for `fold
test` to print an envelope. T4 owns the real CLI wiring and output discipline.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

DEFAULT_CATALOG_DIR = Path(__file__).resolve().parent.parent / "folds" / "catalog_defs"


def _catalog_dir(args: argparse.Namespace) -> Path:
    if getattr(args, "dir", None):
        return Path(args.dir)
    env = os.environ.get("ASG_FOLD_DIR")
    if env:
        return Path(env)
    return DEFAULT_CATALOG_DIR


def _cmd_fold_list(args: argparse.Namespace) -> int:
    from asg_ledger.folds import Catalog

    catalog = Catalog(_catalog_dir(args))
    for entry in catalog.list_entries():
        print(f"{entry.definition.fold_id}\t{entry.digest}\t{entry.source_path}")
    errors = catalog.list_errors()
    for err in errors:
        print(f"ERROR {err.source_path}: {err.reason}: {err.message}", file=sys.stderr)
    return 1 if errors else 0


def _cmd_fold_lint(args: argparse.Namespace) -> int:
    from asg_ledger.folds.errors import FoldDefinitionError
    from asg_ledger.folds.loader import load_definition_file

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
    from asg_ledger.folds import Catalog
    from asg_ledger.folds.engine import evaluate_one
    from asg_ledger.folds.errors import FoldDefinitionError, FoldDeterminismError
    from asg_ledger.folds.loader import load_definition_file

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


def _parse_cap_args(items: list[str]) -> dict[str, int] | None:
    caps_minor: dict[str, int] = {}
    for item in items or []:
        cls, sep, value = item.partition("=")
        if not sep:
            print(f"--cap must be CLASS=MINOR_UNITS, got {item!r}", file=sys.stderr)
            return None
        try:
            caps_minor[cls] = int(value)
        except ValueError:
            print(f"--cap value must be an integer (minor units), got {item!r}", file=sys.stderr)
            return None
    return caps_minor


def _cmd_guard_dry_run(args: argparse.Namespace) -> int:
    from agent_action_capsule import compute_capsule_id

    from asg_ledger.folds.loader import load_definition_file
    from asg_ledger.report import build_dry_run_report, render_report_html
    from asg_ledger.report.render import decode_fragment, to_fragment_payload

    if bool(args.model_note) != bool(args.model_id):
        print("--model-note and --model-id must be given together (or neither)", file=sys.stderr)
        return 1

    caps_minor = _parse_cap_args(args.cap)
    if caps_minor is None:
        return 1

    since = None if args.since in (None, "all") else args.since
    caps_fold = load_definition_file(_catalog_dir(args) / "spend.weekly.yaml")

    def _build():
        return build_dry_run_report(
            args.ledger,
            caps_fold=caps_fold,
            since=since,
            caps_minor=caps_minor,
            operator=args.operator,
            model_note=args.model_note,
            model_id=args.model_id,
        )

    report = _build()
    html, fragment = render_report_html(report)
    out_path = Path(args.out)
    out_path.write_text(html, encoding="utf-8")
    url = f"file://{out_path.resolve()}#{fragment}"

    print(f"wrote {out_path}")
    if args.share:
        print(url)

    if args.verify:
        written_payload = decode_fragment(fragment)
        rebuilt_payload = to_fragment_payload(_build())
        # exclude generated_at: the one field that legitimately differs
        # between two otherwise-identical replays (it's a wall-clock
        # generation timestamp, not derived from the ledger).
        lhs = {k: v for k, v in written_payload.items() if k != "generated_at"}
        rhs = {k: v for k, v in rebuilt_payload.items() if k != "generated_at"}
        if lhs != rhs:
            print("FAIL: replaying the same ledger did not reproduce the same report", file=sys.stderr)
            return 1

        mismatches = []
        for section in written_payload["guards"]:
            for row in section["rows"]:
                for capsule in (row.get("capsule"), row.get("cited_capsule")):
                    if not capsule:
                        continue
                    if compute_capsule_id(capsule) != capsule.get("capsule_id"):
                        mismatches.append(capsule.get("capsule_id"))
        if mismatches:
            print(f"FAIL: {len(mismatches)} cited capsule(s) do not re-verify", file=sys.stderr)
            return 1
        print("OK: report is reproducible and every cited capsule verifies")

    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="asg", description="asg-ledger control plane")
    parser.add_argument("--version", action="store_true", help="print the version and exit")
    sub = parser.add_subparsers(dest="command")

    fold = sub.add_parser("fold", help="fold catalog: list, new, test, lint (full CLI lands in a later task)")
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

    guard = sub.add_parser("guard", help="guard API: dry-run replay + report (full CLI lands in a later task)")
    guard_sub = guard.add_subparsers(dest="guard_command")
    guard.set_defaults(guard_parser=guard)

    p_dry_run = guard_sub.add_parser(
        "dry-run", help="replay a ledger through the guard checks and emit a self-contained HTML report"
    )
    p_dry_run.add_argument("--ledger", required=True, action="append", help="ledger JSONL file or LedgerStore directory (repeatable)")
    p_dry_run.add_argument("--since", default="7d", help="rolling window, e.g. '7d' (anchored to the ledger's own latest record); 'all' for no filter")
    p_dry_run.add_argument("--share", action="store_true", help="print the full shareable file://...#<fragment> URL")
    p_dry_run.add_argument("--verify", action="store_true", help="re-replay and re-verify every cited capsule before exiting")
    p_dry_run.add_argument("--out", default="dry-run-report.html", help="output HTML path (default: dry-run-report.html)")
    p_dry_run.add_argument("--operator", default=None, help="override the displayed operator label (default: the ledger's own)")
    p_dry_run.add_argument(
        "--cap", action="append", default=[], metavar="CLASS=MINOR_UNITS",
        help="per-action-class cap for the caps check, e.g. money.transfer=10000000 (repeatable; omit an action "
        "class to leave it unconfigured -- it will never trigger the caps guard, matching GuardEngine's own default)",
    )
    p_dry_run.add_argument("--model-note", default=None, help="optional pre-written model commentary quote (never generated by this CLI)")
    p_dry_run.add_argument("--model-id", default=None, help="model id the note above was drafted by (required together with --model-note)")
    p_dry_run.add_argument("--dir", help="fold catalog directory the caps check's fold definition lives in (default: built-in catalog, or $ASG_FOLD_DIR)")
    p_dry_run.set_defaults(func=_cmd_guard_dry_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.version:
        from asg_ledger import __version__

        print(__version__)
        return 0

    if args.command == "fold":
        if getattr(args, "fold_command", None) is None:
            args.fold_parser.print_help()
            return 0
        return args.func(args)

    if args.command == "guard":
        if getattr(args, "guard_command", None) is None:
            args.guard_parser.print_help()
            return 0
        return args.func(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
