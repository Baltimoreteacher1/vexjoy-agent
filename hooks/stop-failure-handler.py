#!/usr/bin/env python3
"""StopFailure hook: record session failure for pattern analysis.

Fires when a session ends due to an API error. Appends a failure record
to ~/.claude/state/session-failures.jsonl for later analysis.

History: this hook previously recorded only {timestamp, event, cwd}. It never
read stdin, so 1,374 accumulated rows could not answer the one question the file
exists for -- "what keeps failing". It logged that *something* failed, 1,374
times, with no error, no session, no shape.

Design notes:
- Read the payload off stdin and keep the fields that identify the failure.
  Per verified capture on 2.1.x, failure events carry a top-level `error`
  string and `hook_event_name` is authoritative. See memory
  project_hook_payload_shapes.
- Record `payload_keys` unconditionally. If the StopFailure payload differs
  from what is assumed here, the JSONL says so directly, instead of quietly
  writing nulls forever. That is the difference between instrumentation that
  can be debugged and instrumentation that cannot.
- Never fail, never block, never raise.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Keep the file greppable and bounded; API error strings can be very long.
MAX_ERROR_CHARS = 2000


def _read_payload() -> dict:
    """Best-effort read of the hook payload from stdin. Never raises."""
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return {}
        raw = sys.stdin.read()
    except Exception:
        return {}
    if not raw or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        # Unparseable payload is itself a finding worth keeping.
        return {"_unparsed": raw[:MAX_ERROR_CHARS]}
    return data if isinstance(data, dict) else {"_payload": str(data)[:MAX_ERROR_CHARS]}


def _scalar(value):
    """Return value if it is a small scalar worth recording, else None."""
    if isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:MAX_ERROR_CHARS]
    return None


def main():
    try:
        payload = _read_payload()

        error = payload.get("error")
        if not isinstance(error, str):
            # Some events nest the message; fall back without inventing a schema.
            error = payload.get("message") if isinstance(payload.get("message"), str) else None

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": "stop_failure",
            "cwd": payload.get("cwd") or os.getcwd(),
            # Identity: lets a failure be traced back to a transcript.
            "session_id": _scalar(payload.get("session_id")),
            "hook_event_name": _scalar(payload.get("hook_event_name")),
            "transcript_path": _scalar(payload.get("transcript_path")),
            # The actual failure.
            "error": error[:MAX_ERROR_CHARS] if isinstance(error, str) else None,
            "is_interrupt": _scalar(payload.get("is_interrupt")),
            "duration_ms": _scalar(payload.get("duration_ms")),
            # Self-documenting shape: proves whether the fields above exist.
            "payload_keys": sorted(payload.keys()) if payload else [],
        }

        state_dir = Path.home() / ".claude" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        failures_file = state_dir / "session-failures.jsonl"
        with open(failures_file, "a") as f:
            f.write(json.dumps(record) + "\n")

    except Exception:
        pass  # Hook must never fail itself

    sys.exit(0)


if __name__ == "__main__":
    main()
