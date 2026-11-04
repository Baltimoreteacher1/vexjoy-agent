"""Runtime health record for hooks that run inside a dispatcher.

Why this exists: a hook that starts failing silently is worse than no hook at
all. The dispatchers already catch every guard exception so one bad hook cannot
take down the chain - but that means the failure is swallowed and nobody hears
about it. This records those swallowed failures so hook-health-report.py can
surface them at the next SessionStart.

Only dispatcher-run hooks get runtime coverage. Hooks wired directly into
settings.json are covered by the static checks in hook-health-report.py.

The log is bounded and append-only. Recording must never raise: a failure in
the failure recorder would be the worst possible bug here.
"""

import json
import os
import time
from pathlib import Path

LOG = Path.home() / ".claude" / "logs" / "hook-health.jsonl"

# Keep the tail only. Each record is ~200B, so this caps the file near 60KB.
MAX_RECORDS = 300

# Records older than this are noise - a hook that broke a month ago and was
# fixed should not keep showing up in the report.
MAX_AGE_SECONDS = 14 * 24 * 60 * 60


def record_failure(hook_name: str, exc: BaseException, event: str = "") -> None:
    """Append one hook failure. Never raises."""
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": time.time(),
            "hook": hook_name,
            "event": event,
            "error": f"{type(exc).__name__}: {exc}"[:400],
            "session": os.environ.get("CLAUDE_SESSION_ID", ""),
        }
        with LOG.open("a") as f:
            f.write(json.dumps(entry) + "\n")
        _trim()
    except Exception:
        pass


def read_failures(since_seconds: int = MAX_AGE_SECONDS) -> list[dict]:
    """Return recent failure records, newest last. Never raises."""
    try:
        if not LOG.exists():
            return []
        cutoff = time.time() - since_seconds
        out = []
        for line in LOG.read_text(errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except Exception:
                continue
            if entry.get("ts", 0) >= cutoff:
                out.append(entry)
        return out
    except Exception:
        return []


def clear() -> None:
    """Drop the log. Used after the report acknowledges the failures."""
    try:
        LOG.unlink(missing_ok=True)
    except Exception:
        pass


def _trim() -> None:
    try:
        lines = LOG.read_text(errors="ignore").splitlines()
        if len(lines) > MAX_RECORDS:
            tmp = LOG.with_suffix(".jsonl.tmp")
            tmp.write_text("\n".join(lines[-MAX_RECORDS:]) + "\n")
            tmp.replace(LOG)
    except Exception:
        pass
