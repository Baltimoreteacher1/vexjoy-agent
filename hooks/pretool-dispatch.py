#!/usr/bin/env python3
# hook-version: 2.0.0
"""PreToolUse dispatcher: run the whole PreToolUse guard chain in ONE interpreter.

Why: this started life as pretool-bash-dispatch.py, which collapsed the seven
Bash guards into one process. The other PreToolUse matchers were left as
separate settings.json entries, so they kept paying a fresh interpreter each:

  Edit      6 processes  ~470ms   (unified-gate, learning-injector,
                                   prompt-injection-scanner, config-protection,
                                   file-backup, suggest-compact)
  Write     4 processes  ~310ms
  mcp__.*   2 processes  ~150ms
  Agent     2 processes  ~160ms

Measured on this machine, on every single tool call. The guards themselves are
cheap - the process starts were the cost. Editing is the hottest path, so it was
also the worst hit.

This runs every guard, in the same order the settings.json groups fired them,
in this process, and applies each guard's matcher itself.

Contract preserved exactly (verified against all fifteen guards):
  - Every guard exits 0 always. A block is signalled by printing a JSON object
    carrying hookSpecificOutput.permissionDecision to STDOUT. Diagnostics go to
    STDERR.
  - So: forward each guard's stderr untouched, inspect its stdout, and stop at
    the first guard that returns a deny/ask decision - which is what the
    sequential chain did, since Claude Code honours the first decision it sees.
  - Non-decision stdout (e.g. ci-merge-gate's WARNING lines, the learning
    injector's context) is preserved, but MERGED rather than concatenated.
    This matters: sequentially, Claude Code parsed each guard's stdout on its
    own, so three guards each printing the no-op envelope
    {"hookSpecificOutput": {"hookEventName": "PreToolUse"}} was three valid
    documents. In one process that becomes one stdout stream, and three
    concatenated JSON objects are not a valid document. So no-op envelopes are
    dropped, real content is merged, and at most one well-formed envelope is
    emitted - the same approach posttool-dispatch.py takes.
  - Fail OPEN. A guard that raises is logged to stderr and skipped, matching the
    existing per-hook `except: pass` posture. A dispatcher that failed closed
    would turn any bug here into a total tool-call outage.

CHAIN order is the exact order these fired as separate settings.json entries,
so first-decision-wins resolves identically to the old configuration.

Guards keep working standalone; nothing about their files changes.
"""

import io
import json
import os
import re
import runpy
import sys
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(HOOKS_DIR / "lib"))

try:
    import hook_health
except Exception:  # pragma: no cover - health recording is best effort
    hook_health = None

# (script, matcher) - matcher is a Claude Code tool-name regex, or None for all.
# Order below == the order the old settings.json groups were evaluated in:
#   1. mcp__.*     blast-radius guard, then mcp health check
#   2. Write|Edit  unified gate
#   3. Bash        the seven-guard Bash chain
#   4. Edit        learning injector
#   5. Write|Edit  prompt-injection scanner, then config protection
#   6. Edit        file backup
#   7. Agent       reference-loading enforcer, then subagent warmstart
#   8. Write|Edit  suggest-compact
# pretool-unified-gate and pretool-learning-injector appear once each, with the
# union of the matchers they were registered under, so neither double-runs.
CHAIN = [
    ("pretool-mcp-blast-radius-guard.py", r"mcp__.*"),
    ("mcp-health-check.py", r"mcp__.*"),
    ("pretool-unified-gate.py", r"Bash|Write|Edit"),
    ("pretool-branch-safety.py", r"Bash"),
    ("ci-merge-gate.py", r"Bash"),
    ("pretool-classroom-deploy-guard.py", r"Bash"),
    ("pretool-git-stray-ref-detector.py", r"Bash"),
    ("pretool-ref-delete-guard.py", r"Bash"),
    ("pretool-learning-injector.py", r"Bash|Edit"),
    ("pretool-prompt-injection-scanner.py", r"Write|Edit"),
    ("pretool-config-protection.py", r"Write|Edit"),
    ("pretool-file-backup.py", r"Edit"),
    ("reference-loading-enforcer.py", r"Agent"),
    ("pretool-subagent-warmstart.py", r"Agent"),
    ("suggest-compact.py", r"Write|Edit"),
]

BLOCKING_DECISIONS = {"deny", "ask"}


def _matches(matcher: str | None, tool_name: str) -> bool:
    """Apply a Claude Code matcher to a tool name.

    Matchers are regexes, so this handles both the plain alternations
    ("Write|Edit") and the MCP wildcard ("mcp__.*") the same way Claude Code
    does. A guard with no matcher runs for every tool.
    """
    if not matcher:
        return True
    try:
        return re.fullmatch(matcher, tool_name) is not None
    except re.error:  # pragma: no cover - a malformed matcher must not block
        return False


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


def _harvest(stdout_text: str, contexts: list[str], messages: list[str]) -> None:
    """Pull context/message content out of one guard's stdout.

    JSON envelopes contribute their fields; anything else is plain text a guard
    meant Claude to see, so it is carried through as context. A bare
    {"hookSpecificOutput": {"hookEventName": "PreToolUse"}} is a no-op and
    contributes nothing.
    """
    text = stdout_text.strip()
    if not text:
        return
    for chunk in text.split("\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        if chunk.startswith("{"):
            try:
                obj = json.loads(chunk)
            except Exception:
                contexts.append(chunk)
                continue
            inner = obj.get("hookSpecificOutput") or {}
            if inner.get("additionalContext"):
                contexts.append(inner["additionalContext"])
            if inner.get("userMessage"):
                messages.append(inner["userMessage"])
        else:
            contexts.append(chunk)


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
            f"[pretool-dispatch] {path.name} raised {type(exc).__name__}: {exc} (skipped, failing open)",
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

    try:
        tool_name = json.loads(payload).get("tool_name", "")
    except Exception:
        tool_name = ""

    # PRETOOL_DISPATCH_ONLY runs a single guard regardless of matcher, for tests
    # and bisecting. BASH_DISPATCH_ONLY is the name this accepted as
    # pretool-bash-dispatch.py; still honoured so existing callers keep working.
    only = os.environ.get("PRETOOL_DISPATCH_ONLY") or os.environ.get("BASH_DISPATCH_ONLY")

    contexts: list[str] = []
    messages: list[str] = []

    for name, matcher in CHAIN:
        if only and name != only:
            continue
        if not only and not _matches(matcher, tool_name):
            continue
        path = HOOKS_DIR / name
        if not path.exists():
            print(f"[pretool-dispatch] missing guard {name} (skipped)", file=sys.stderr)
            continue
        out = _run_guard(path, payload)
        decision = _decision_of(out)
        if decision is not None:
            # First decision wins; emit it and stop, as the sequential chain did.
            # Context gathered by earlier guards is dropped along with the call
            # they were describing, which is what the sequential chain did too.
            print(json.dumps(decision))
            sys.exit(0)
        _harvest(out, contexts, messages)

    inner = {"hookEventName": "PreToolUse"}
    if contexts:
        inner["additionalContext"] = "\n".join(contexts)
    if messages:
        inner["userMessage"] = "\n".join(messages)
    print(json.dumps({"hookSpecificOutput": inner}))
    sys.exit(0)


if __name__ == "__main__":
    main()
