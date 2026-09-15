#!/usr/bin/env python3
# hook-version: 1.0.0
"""PostToolUse Hook: Record wasted tokens from tool failures for ROI tracking.

Estimates token waste when tools fail and feeds learning-db.py record-waste
for ROI computation. The waste estimate uses output length / 4 (rough
chars-to-tokens ratio) with a minimum floor of 100 tokens.

ADR-032 Phase 1 — TRACK component.

Design:
- SILENT always (no stdout output to Claude)
- Non-blocking (always exits 0)
- Fast execution (<50ms target, no heavy imports)
- Records every failure immediately (no batching — failures are rare)
"""

import json
import os
import subprocess
import sys
from pathlib import Path

# Add lib directory to path for imports
sys.path.insert(0, str(Path(__file__).parent / "lib"))

from hook_utils import get_session_id
from stdin_timeout import read_stdin

# Minimum token waste estimate per failure
MIN_WASTE_TOKENS = 100

# Rough chars-to-tokens ratio (1 token ~ 4 chars)
CHARS_PER_TOKEN = 4


def main() -> None:
    """Record wasted tokens when a tool execution fails."""
    try:
        hook_input = json.loads(read_stdin(timeout=2))

        # Verified against live 2.1.236 captures: a failed tool call arrives as
        # PostToolUseFailure with a top-level "error" string. PostToolUse fires
        # on success only and carries "tool_response" — never the "tool_result"
        # /"is_error" shape this hook was originally written against, which is
        # why it recorded nothing.
        output = hook_input.get("error")
        if not (isinstance(output, str) and output.strip()):
            result = hook_input.get("tool_response") or hook_input.get("tool_result") or {}
            if isinstance(result, dict) and result.get("is_error"):
                output = str(result.get("output") or result.get("error") or "")
            else:
                return  # Not a failure — nothing to record

        waste_tokens = max(len(output) // CHARS_PER_TOKEN, MIN_WASTE_TOKENS)

        # The event carries the real session_id. The shared get_session_id()
        # helper only reads CLAUDE_SESSION_ID (unset in hook subprocesses) and
        # otherwise derives a PPID+time hash, so waste was being filed under a
        # synthetic id that matches no session — making the ROI numbers
        # unattributable. Prefer the payload; keep the helper as a fallback.
        session_id = hook_input.get("session_id") or get_session_id()

        repo_root = Path(__file__).resolve().parent.parent
        script = repo_root / "scripts" / "learning-db.py"
        if not script.exists():
            return

        subprocess.run(
            [
                sys.executable,
                str(script),
                "record-waste",
                "--session",
                session_id,
                "--tokens",
                str(waste_tokens),
            ],
            capture_output=True,
            timeout=5,
        )

    except (json.JSONDecodeError, subprocess.TimeoutExpired, OSError, Exception) as e:
        if os.environ.get("CLAUDE_HOOKS_DEBUG"):
            import traceback

            print(f"[record-waste] HOOK-ERROR: {type(e).__name__}: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
    finally:
        sys.exit(0)


if __name__ == "__main__":
    main()
