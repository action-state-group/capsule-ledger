# SPDX-License-Identifier: Apache-2.0
"""``asg guard`` verbs: dry-run replay + self-contained HTML report (moved
here, matching ``fold_cmds.py``'s per-verb-module convention, so ``main.py``
stays a thin dispatcher), plus ``guard enforce`` -- a minimal, honest local
marker command (see ``_cmd_guard_enforce``'s own docstring for exactly what
it does and doesn't do).

Every guard-dry-run invocation here checks the current packaging arm
(``asg_ledger.packaging``) and, in "guards-only", both suppresses the
evidence chrome in the rendered HTML report (``render_report_html``'s own
``arm`` param) and rewords/suppresses this command's own stdout so it never
prints a capsule id or a share/verify link -- see this module's inline
comments at each print site.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .. import packaging

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

    from ..folds.loader import load_definition_file
    from ..report import build_dry_run_report, render_report_html
    from ..report.render import TelemetryConfig, decode_fragment, to_fragment_payload
    from ..telemetry.record import record_evidence_touch, record_guard_configured, record_guard_evaluated

    if bool(args.model_note) != bool(args.model_id):
        print("--model-note and --model-id must be given together (or neither)", file=sys.stderr)
        return 1

    caps_minor = _parse_cap_args(args.cap)
    if caps_minor is None:
        return 1

    arm = packaging.current_arm()
    evidence_visible = packaging.evidence_visible(arm)

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

    telemetry = None
    if args.telemetry_opt_in and args.telemetry_endpoint:
        telemetry = TelemetryConfig(opted_in=True, endpoint=args.telemetry_endpoint)

    html, fragment = render_report_html(report, arm=arm, telemetry=telemetry)
    out_path = Path(args.out)
    out_path.write_text(html, encoding="utf-8")
    url = f"file://{out_path.resolve()}#{fragment}"

    print(f"wrote {out_path}")
    # Arm A ("guards-only"): the share link is a verify-link suggestion --
    # not printed, matching the report itself never surfacing its evidence
    # chrome. The file above still exists and is still openable; this CLI
    # just doesn't advertise the fragment-carried permalink.
    if args.share and evidence_visible:
        print(url)

    if caps_minor:
        record_guard_configured(arm)
    if report.actions_replayed:
        record_guard_evaluated(arm)
    if evidence_visible and (args.share or args.verify):
        record_evidence_touch(arm)

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
            # Arm A: "cited record(s)", never the word "capsule" in output.
            noun = "cited capsule(s)" if evidence_visible else "cited record(s)"
            print(f"FAIL: {len(mismatches)} {noun} do not re-verify", file=sys.stderr)
            return 1
        tail = " and every cited capsule verifies" if evidence_visible else ""
        print(f"OK: report is reproducible{tail}")

    return 0


def _cmd_guard_enforce(args: argparse.Namespace) -> int:
    """Records, locally, that this install has moved from dry-run to
    enforce -- nothing more. ``GuardEngine.check(..., dry_run=...)`` is
    already a real parameter your own integration code controls (this CLI
    only ever drives it in dry-run mode via ``guard dry-run``); this
    command does not gate anything itself. It exists so there is a real,
    minimal, honest action to record the M2 ("enforcement-on") telemetry
    fact against, matching the report's own "$ asg guard enforce" callout.
    """
    from ..telemetry.record import record_enforcement_flip

    arm = packaging.current_arm()
    record_enforcement_flip(arm)
    print(
        "recorded: this install has moved from dry-run to enforce (locally, opt-in telemetry only).\n"
        "This command does not itself gate actions -- wire GuardEngine.check(..., dry_run=False) into "
        "your own integration to actually enforce."
    )
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
    p_dry_run.add_argument(
        "--share", action="store_true",
        help="print the full shareable file://...#<fragment> URL (no-op in the guards-only packaging arm)",
    )
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
    p_dry_run.add_argument(
        "--telemetry-opt-in", action="store_true",
        help="embed a disclosed, anonymous open-beacon in the report for the M6 (viral unit) metric -- "
        "requires --telemetry-endpoint too, and is off by default; see `asg telemetry status`",
    )
    p_dry_run.add_argument(
        "--telemetry-endpoint", default=os.environ.get("ASG_LEDGER_TELEMETRY_ENDPOINT"),
        help="where the open-beacon above (if enabled) sends its single anonymous event (default: "
        "$ASG_LEDGER_TELEMETRY_ENDPOINT, or none -- with no endpoint the beacon is never embedded)",
    )
    p_dry_run.set_defaults(func=_cmd_guard_dry_run)

    p_enforce = guard_sub.add_parser(
        "enforce", help="record locally that this install has moved from dry-run to enforce (telemetry marker only)"
    )
    p_enforce.set_defaults(func=_cmd_guard_enforce)

    return guard
