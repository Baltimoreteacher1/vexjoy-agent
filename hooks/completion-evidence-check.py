#!/usr/bin/env python3
"""PostToolUse hook: detect completion claims without test evidence.

Scans tool output for completion language and checks whether test evidence
is present. If completion is claimed without evidence, prints an advisory
warning (ADR-125).

Input: PostToolUse event JSON on stdin; tool output read from `tool_result`.
Always exits 0 (advisory, never blocking).
"""

import json
import re
import sys

# Pre-compiled patterns for speed
COMPLETION_PATTERN = re.compile(
    r"(?:task\s+complete|done|finished|all\s+set|looks\s+good|should\s+work"
    r"|I've\s+implemented|I've\s+fixed|changes\s+are\s+ready)",
    re.IGNORECASE,
)

EVIDENCE_PATTERN = re.compile(
    r"(?:PASS|ok\s|passed|exit\s+0|\u2713|tests\s+pass|green|SUCCESS)",
    re.IGNORECASE,
)


def _extract_output(event):
    """Pull text from the PostToolUse `tool_result` field (str or {type,text})."""
    result = event.get("tool_result", event.get("tool_response", ""))
    if isinstance(result, dict):
        return result.get("text", "") or ""
    if isinstance(result, list):
        return " ".join(
            (b.get("text", "") if isinstance(b, dict) else str(b)) for b in result
        )
    return str(result or "")


def main():
    try:
        raw = sys.stdin.read()
        if not raw:
            return
        event = json.loads(raw)
        output = _extract_output(event)
        if not output:
            return

        if COMPLETION_PATTERN.search(output):
            if not EVIDENCE_PATTERN.search(output):
                print(
                    "[completion-check] Completion claimed without test evidence. "
                    "Required: run tests and show output before marking complete."
                )
    except (json.JSONDecodeError, ValueError):
        return
    except Exception as e:
        import os

        if os.environ.get("CLAUDE_HOOKS_DEBUG"):
            print(
                f"[completion-check] HOOK-ERROR: {type(e).__name__}: {e}",
                file=sys.stderr,
            )


if __name__ == "__main__":
    main()
    sys.exit(0)
