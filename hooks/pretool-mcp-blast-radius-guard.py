#!/usr/bin/env python3
# hook-version: 1.0.0
"""
PreToolUse:mcp__* Hook: MCP Blast-Radius Guard

WHY THIS EXISTS
---------------
settings.json runs with `"defaultMode": "bypassPermissions"`. Every guardrail in
this directory is wired to a `Bash|Write|Edit|Agent` matcher, so NOTHING sits in
front of MCP tool calls -- and several connected MCP servers reach live systems:

  - cloudflare-bindings  -> production D1 (student progress / gradebook data)
  - claude-memory        -> the persistent memory Postgres
  - Shopify              -> a LIVE storefront (jewishearrings) with real orders
  - Gmail                -> outbound mail sent AS the user

The `permissions.deny` list already blocks the MCP tools whose NAME is the
danger (`d1_database_delete`, `r2_bucket_delete`, ...). Name matching cannot
reach the dangerous calls, because for those the danger is in the ARGUMENTS:
`d1_database_query` will happily run `DROP TABLE`, and `graphql_mutation` will
happily run `productDelete`. Both are spelled identically to a harmless read.

This hook reads the arguments. It blocks the destructive shapes and leaves
ordinary reads, inserts, and updates alone.

FAILS OPEN. A crash here must never hand back the ability to drop a table, so
settings.json keeps its name-based denies as the belt-and-braces layer.

Bypass for a genuinely intended destructive call: MCP_BLAST_RADIUS_BYPASS=1
"""

import json
import os
import re
import sys
import traceback

# --- SQL-bearing tools: block DDL/mass-DML, allow reads and scoped writes ----
SQL_TOOLS = {
    "mcp__cloudflare-bindings__d1_database_query": "sql",
    "mcp__claude-memory__execute_sql": "sql",
}

# Statements that destroy schema or data wholesale.
SQL_DESTRUCTIVE = re.compile(
    r"\b(?:"
    r"DROP\s+(?:TABLE|DATABASE|SCHEMA|INDEX|VIEW|TRIGGER)"
    r"|TRUNCATE\s+(?:TABLE\s+)?"
    r"|ALTER\s+TABLE\s+\S+\s+DROP"
    r"|DELETE\s+FROM"
    r"|UPDATE\s+"
    r")",
    re.IGNORECASE,
)

# A DELETE/UPDATE with a real WHERE is a normal scoped write, not a blast.
SQL_SCOPED = re.compile(r"\bWHERE\b", re.IGNORECASE)
SQL_UNSCOPABLE = re.compile(r"\b(?:DROP|TRUNCATE)\b", re.IGNORECASE)

# --- Shopify: a live storefront. Block deletes/cancels/refunds. -------------
SHOPIFY_MUTATION_TOOLS = {"mcp__claude_ai_Shopify__graphql_mutation"}
SHOPIFY_DESTRUCTIVE = re.compile(
    r"\b(?:"
    r"\w*Delete\b"
    r"|orderCancel|orderClose|refundCreate|orderEditCommit"
    r"|customerDelete|inventoryDeactivate"
    r"|productVariantsBulkDelete|bulkOperationCancel"
    r")",
    re.IGNORECASE,
)

# --- Outbound mail sent as the user. Drafts stay allowed. -------------------
OUTBOUND_TOOLS = {
    "mcp__claude_ai_Gmail__send_message": "sends mail as you",
    "mcp__claude_ai_Gmail__forward": "forwards mail as you",
    "mcp__claude_ai_Gmail__reply": "replies as you",
}


def deny(tag, reason):
    print(f"[mcp-blast-radius-guard] BLOCKED: {tag}", file=sys.stderr)
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )
    sys.exit(0)


def collect_strings(obj, out):
    """MCP arg shapes vary by server; gather every string value."""
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            collect_strings(v, out)
    elif isinstance(obj, list):
        for v in obj:
            collect_strings(v, out)


def main():
    if os.environ.get("MCP_BLAST_RADIUS_BYPASS") == "1":
        sys.exit(0)

    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # fail open

    tool = payload.get("tool_name", "")
    if not tool.startswith("mcp__"):
        sys.exit(0)

    tool_input = payload.get("tool_input", {}) or {}
    strings = []
    collect_strings(tool_input, strings)
    blob = "\n".join(strings)

    if tool in OUTBOUND_TOOLS:
        deny(
            f"{tool} ({OUTBOUND_TOOLS[tool]})",
            "Sending mail from your account is a human decision. "
            "Create a draft instead (create_draft / update_draft) and send it yourself, "
            "or re-run with MCP_BLAST_RADIUS_BYPASS=1 if you explicitly authorized this send.",
        )

    if tool in SQL_TOOLS:
        for stmt in strings:
            if not SQL_DESTRUCTIVE.search(stmt):
                continue
            # A scoped UPDATE/DELETE is ordinary work; DROP/TRUNCATE never is.
            if SQL_SCOPED.search(stmt) and not SQL_UNSCOPABLE.search(stmt):
                continue
            deny(
                f"{tool} destructive SQL",
                "This statement drops, truncates, or rewrites rows without a WHERE clause "
                f"against live data ({tool}). Verify a current backup, then run it yourself "
                "or set MCP_BLAST_RADIUS_BYPASS=1 for this session.",
            )

    if tool in SHOPIFY_MUTATION_TOOLS and SHOPIFY_DESTRUCTIVE.search(blob):
        deny(
            f"{tool} destructive storefront mutation",
            "This mutation deletes, cancels, or refunds on a LIVE storefront with real "
            "customer orders. Confirm with the store owner first, then run it yourself "
            "or set MCP_BLAST_RADIUS_BYPASS=1.",
        )

    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        if os.environ.get("CLAUDE_HOOKS_DEBUG"):
            traceback.print_exc(file=sys.stderr)
        else:
            print(f"[mcp-blast-radius-guard] Error: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(0)  # fail open
