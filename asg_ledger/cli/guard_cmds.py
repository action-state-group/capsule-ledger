# SPDX-License-Identifier: Apache-2.0
"""``asg guard`` verbs: dry-run replay + self-contained HTML report (moved
here, matching ``fold_cmds.py``'s per-verb-module convention, so ``main.py``
stays a thin dispatcher)."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

__all__ = ["add_parser"]

DEFAULT_CATALOG_DIR = Path(__file__).resolve().parent.parent / "folds" / "catalog_defs"


def _catalog_dir(args: argparse.Namespace) -> Path:
    if getattr(args, "dir", None):
        return Path(args.dir)
    env = os.environ.get("ASG_FOLD_DIR")
    if env:
        return Path(env)
    return DEFAULT_CATALOG_DIR


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


def add_parser(sub: argparse._SubParsersAction) -> argparse.ArgumentParser:
    guard = sub.add_parser("guard", help="guard API: dry-run replay + report (full CLI lands in a later task)")
    guard_sub = guard.add_subparsers(dest="guard_command")
    guard.set_defaults(guard_parser=guard)

    p_dry_run = guard_sub.add_parser(
        "dry-run", help="replay a ledger through the guard checks and emit a self-contained HTML report"
    )
    p_dry_run.add_argument(
        "--ledger", required=True, action="append", help="ledger JSONL file or LedgerStore directory (repeatable)"
    )
    p_dry_run.add_argument(
        "--since", default="7d",
        help="rolling window, e.g. '7d' (anchored to the ledger's own latest record); 'all' for no filter",
    )
    p_dry_run.add_argument("--share", action="store_true", help="print the full shareable file://...#<fragment> URL")
    p_dry_run.add_argument(
        "--verify", action="store_true", help="re-replay and re-verify every cited capsule before exiting"
    )
    p_dry_run.add_argument("--out", default="dry-run-report.html", help="output HTML path (default: dry-run-report.html)")
    p_dry_run.add_argument(
        "--operator", default=None, help="override the displayed operator label (default: the ledger's own)"
    )
    p_dry_run.add_argument(
        "--cap", action="append", default=[], metavar="CLASS=MINOR_UNITS",
        help="per-action-class cap for the caps check, e.g. money.transfer=10000000 (repeatable; omit an action "
        "class to leave it unconfigured -- it will never trigger the caps guard, matching GuardEngine's own default)",
    )
    p_dry_run.add_argument(
        "--model-note", default=None, help="optional pre-written model commentary quote (never generated by this CLI)"
    )
    p_dry_run.add_argument(
        "--model-id", default=None, help="model id the note above was drafted by (required together with --model-note)"
    )
    p_dry_run.add_argument(
        "--dir", help="fold catalog directory the caps check's fold definition lives in (default: built-in catalog, or $ASG_FOLD_DIR)"
    )
    p_dry_run.set_defaults(func=_cmd_guard_dry_run)

    return guard
