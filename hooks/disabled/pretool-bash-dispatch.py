#!/usr/bin/env python3
# hook-version: 1.0.0
"""PreToolUse dispatcher: run the Bash guard chain in ONE interpreter.

Why: the Bash guard chain was seven separate `python3 <hook>.py` invocations.
Each paid a fresh interpreter start plus its own imports; measured end to end at
~298ms per Bash tool call, on every Bash tool call. The guards themselves are
cheap - the process starts were the cost.

This runs the same seven guards, in the same order, in this process.

Contract preserved exactly (verified against all seven):
  - Every guard exits 0 always. A block is signalled by printing a JSON object
    carrying hookSpecificOutput.permissionDecision to STDOUT. Diagnostics go to
    STDERR.
  - So: forward each guard's stderr untouched, inspect its stdout, and stop at
    the first guard that returns a deny/ask decision - which is what the
    sequential chain did, since Claude Code honours the first decision it sees.
  - Non-decision stdout (e.g. ci-merge-gate's WARNING lines) is forwarded.
  - Fail OPEN. A guard that raises is logged to stderr and skipped, matching the
    existing per-hook `except: pass` posture. A dispatcher that fails closed
    would turn any bug here into a total Bash outage.

Guards keep working standalone; nothing about their files changes.
"""

import io
import json
import os
import runpy
import sys
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(HOOKS_DIR / "lib"))

try:
    import hook_health
except Exception:  # pragma: no cover - health recording is best effort
    hook_health = None

# Order is the exact order these fired as separate settings.json entries:
# the Bash|Write|Edit group, then the Bash group, then the Bash|Edit group.
CHAIN = [
    "pretool-unified-gate.py",
    "pretool-branch-safety.py",
    "ci-merge-gate.py",
    "pretool-classroom-deploy-guard.py",
    "pretool-git-stray-ref-detector.py",
    "pretool-ref-delete-guard.py",
    "pretool-learning-injector.py",
]

BLOCKING_DECISIONS = {"deny", "ask"}


def _decision_of(stdout_text: str):
    """Return the guard's permission decision dict, or None.

    Guards print exactly one JSON object when they decide. Tolerate surrounding
    noise by scanning lines rather than requiring the whole buffer to parse.
    """
    text = stdout_text.strip()
    if not text:
        return None
    candidates = [text] if text.startswith("{") else []
    candidates += [ln for ln in text.splitlines() if ln.strip().startswith("{")]
    for cand in candidates:
        try:
            obj = json.loads(cand)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        decision = (obj.get("hookSpecificOutput") or {}).get("permissionDecision")
        if decision in BLOCKING_DECISIONS:
            return obj
    return None


def _run_guard(path: Path, payload: str) -> str:
    """Run one guard in-process. Returns its stdout. Never raises."""
    saved_stdin, saved_stdout, saved_path = sys.stdin, sys.stdout, list(sys.path)
    buf = io.StringIO()
    sys.stdin = io.StringIO(payload)
    sys.stdout = buf
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit:
        pass  # Every guard ends in sys.exit(0); that is normal termination.
    except Exception as exc:
        print(
            f"[bash-dispatch] {path.name} raised {type(exc).__name__}: {exc} (skipped, failing open)",
            file=sys.stderr,
        )
        if hook_health is not None:
            hook_health.record_failure(path.name, exc, event="PreToolUse")
    finally:
        sys.stdin, sys.stdout, sys.path[:] = saved_stdin, saved_stdout, saved_path
    return buf.getvalue()


def main():
    try:
        payload = sys.stdin.read() if not sys.stdin.isatty() else ""
    except Exception:
        payload = ""

    only = os.environ.get("BASH_DISPATCH_ONLY")
    chain = [c for c in CHAIN if not only or c == only]

    for name in chain:
        path = HOOKS_DIR / name
        if not path.exists():
            print(f"[bash-dispatch] missing guard {name} (skipped)", file=sys.stderr)
            continue
        out = _run_guard(path, payload)
        decision = _decision_of(out)
        if decision is not None:
            # First decision wins; emit it and stop, as the sequential chain did.
            print(json.dumps(decision))
            sys.exit(0)
        if out.strip():
            sys.stdout.write(out if out.endswith("\n") else out + "\n")

    sys.exit(0)


if __name__ == "__main__":
    main()
