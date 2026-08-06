#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Minimal framework-adapter integration: the same `GuardEngine.check()` call
a LangGraph node, CrewAI tool wrapper, or ADK tool handler would make before
letting an agent's action through. No MCP, no subprocess -- this is the
public in-process API (`capsule_ledger.guards`), the same one `capsule-mcp`'s
`intent_declare` tool wraps. See `../onboarding.md` ("Path 3: framework
adapter") for how to run this and confirm the record it produces.

Run: CAPSULE_LEDGER=/some/dir python3 docs/onboarding/framework_adapter_example.py
"""
from __future__ import annotations

import sys

from capsule_ledger.cli.constraints_cmd import DEFAULT_CAPS_FOLD_ID, DEFAULT_CATALOG_DIR
from capsule_ledger.envcompat import env_get
from capsule_ledger.folds.catalog import Catalog
from capsule_ledger.guards import Action, GuardEngine, LocalSigner
from capsule_ledger.ledger import LedgerStore


def main() -> int:
    ledger_dir = env_get("CAPSULE_LEDGER", "ASG_LEDGER")
    if not ledger_dir:
        print("framework_adapter_example: set $CAPSULE_LEDGER to a directory", file=sys.stderr)
        return 2

    # --- one-time setup, e.g. at your app's startup ---
    ledger = LedgerStore(ledger_dir)
    caps_fold = Catalog(DEFAULT_CATALOG_DIR).get(DEFAULT_CAPS_FOLD_ID).definition
    guard = GuardEngine(
        ledger=ledger,
        caps_fold=caps_fold,
        signer_provider=lambda: LocalSigner(key_id="dev", secret=b"dev-secret"),
    )

    # --- the two-line integration point, inside your graph/crew/tool node ---
    action = Action(
        verb="send_invoice_reminder",
        operator="acme-corp",
        developer="langgraph-demo-agent@v1",
        action_class="comms.external",
    )
    decision = guard.check(action)
    # ---------------------------------------------------------------------

    print(f"{decision.outcome} · {decision.capsule.get('capsule_id')}")
    ledger.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
