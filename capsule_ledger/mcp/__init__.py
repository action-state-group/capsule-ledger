# SPDX-License-Identifier: Apache-2.0
"""MCP advisory server exposing the ledger, folds, and guard checks as
structured tools -- nine read-only, plus `intent_declare`, the only tool
that writes (a guard decision, appended as a signed capsule).

See ``server.py`` for the FastMCP wiring and ``tools.py`` for the actual
logic, which is CLI-independent and directly unit-testable.
"""
