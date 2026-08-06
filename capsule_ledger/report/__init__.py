# SPDX-License-Identifier: Apache-2.0
"""Dry-run report artifact: replay a ledger through the guard API in dry-run
mode and render a self-contained, fragment-carried HTML report.

See ``capsule_ledger.report.build.build_dry_run_report`` for the entry point and
``capsule_ledger.report.render.render_report_html`` for the artifact renderer.
"""
from .build import build_dry_run_report
from .model import DryRunReport, GuardSection, ModelNote, ReportRow
from .render import encode_fragment, render_report_html

__all__ = [
    "build_dry_run_report",
    "DryRunReport",
    "GuardSection",
    "ModelNote",
    "ReportRow",
    "render_report_html",
    "encode_fragment",
]
