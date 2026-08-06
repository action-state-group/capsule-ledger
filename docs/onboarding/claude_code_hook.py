#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Minimal Claude Code `PostToolUse` hook: records every matched tool call as a
capsule-ledger capsule via the real `capsule-mcp` server (stdio), so the
ledger captures what actually ran -- not just what an agent chooses to
self-report. See `../onboarding.md` ("Path 1: Claude Code") for the
`settings.json` wiring and how to confirm a record landed.

Deliberately minimal: `verb` is the raw tool name, `target` is a short repr
of the tool input (not JSON -- some MCP clients auto-parse a JSON-looking
string field back into an object, which trips the server's schema
validation; `repr()` sidesteps that). No `action_class` is passed, so every
captured action resolves to the guard's consequential/fail-closed default --
narrow that down with a real classifier before using this past a demo.

Requires `$ASG_LEDGER` to point at a real `LedgerStore` directory (not a
JSONL fixture -- each hook invocation is a fresh, short-lived subprocess, so
a fixture re-imported into a throwaway store per call would not accumulate
records across calls).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def _declare(tool_name: str, tool_input: dict, cwd: str) -> dict:
    params = StdioServerParameters(command="capsule-mcp", args=[], env=dict(os.environ))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "intent_declare",
                {
                    "verb": tool_name,
                    "operator": cwd or "local-session",
                    "developer": os.environ.get("ASG_AGENT_ID", "claude-code@local"),
                    "target": repr(tool_input)[:200],
                },
            )
            text = result.content[0].text
            if result.isError:
                raise RuntimeError(text)
            return json.loads(text)


def main() -> int:
    if not os.environ.get("ASG_LEDGER"):
        print("claude_code_hook: $ASG_LEDGER not set, skipping capture", file=sys.stderr)
        return 0
    event = json.load(sys.stdin)
    outcome = asyncio.run(
        _declare(event.get("tool_name", "(unknown)"), event.get("tool_input") or {}, event.get("cwd", ""))
    )
    print(f"capsule-ledger: {outcome.get('outcome')} · {outcome.get('capsule_id')}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
