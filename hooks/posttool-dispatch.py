#!/usr/bin/env python3
# hook-version: 1.0.0
"""PostToolUse dispatcher: run the PostToolUse chain in ONE interpreter.

Why: the same problem pretool-dispatch.py already solved on the PreToolUse
side. PostToolUse was ten separate `python3 <hook>.py` invocations for an Edit
and eight for a Bash - measured end to end at ~436ms and ~413ms respectively, on
every single tool call. The hooks themselves are cheap; the process starts were
the cost.

This runs the same hooks, in the same order, in this process.

Contract differences from the PreToolUse dispatcher, which matter:

  - PostToolUse hooks do NOT make permission decisions, so there is no
    first-decision-wins short circuit. Every hook in the chain runs, always.
  - Because they all run, their stdout has to be merged. Sequentially, Claude
    Code parsed each hook's stdout independently; here it sees one stream. So
    we merge rather than concatenate: JSON envelopes contribute their
    additionalContext and userMessage, plain text contributes itself, and the
    result is emitted as a single well-formed envelope. Concatenating raw JSON
    objects would produce output Claude Code cannot parse.
  - A hook that emits only the no-op envelope {"hookSpecificOutput":
    {"hookEventName": "PostToolUse"}} contributes nothing, which is correct.

Fail OPEN, same as the PreToolUse dispatcher. A hook that raises is logged to
stderr, recorded for the health report, and skipped. A dispatcher that failed
closed would turn any bug here into a total tool-call outage.

Hooks keep working standalone; nothing about their files changes.
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

# Order is the exact order these fired as separate settings.json entries.
# Matchers are applied per hook below, so this one dispatcher serves every tool.
CHAIN = [
    ("posttool-lint-hint.py", "Write|Edit"),
    ("agent-grade-on-change.py", "Write|Edit"),
    ("posttool-security-scan.py", "Write|Edit"),
    ("retro-graduation-gate.py", "Bash"),
    ("posttool-rename-sweep.py", "Bash"),
    ("posttool-bash-injection-scan.py", "Bash"),
    ("record-activation.py", "Edit|Write|Bash"),
    ("posttool-session-reads.py", "Read"),
    ("usage-tracker.py", "Skill|Agent"),
    ("review-capture.py", "Agent"),
    ("error-learner.py", None),
    ("routing-gap-recorder.py", None),
    ("completion-evidence-check.py", None),
    ("sql-injection-detector.py", "Write|Edit"),
    ("safe-format-after-edit.py", "Write|Edit|MultiEdit"),
]


def _matches(matcher: str | None, tool_name: str) -> bool:
    if not matcher:
        return True
    return tool_name in matcher.split("|")


def _run_hook(path: Path, payload: str) -> str:
    """Run one hook in-process. Returns its stdout. Never raises."""
    saved_stdin, saved_stdout, saved_path = sys.stdin, sys.stdout, list(sys.path)
    buf = io.StringIO()
    sys.stdin = io.StringIO(payload)
    sys.stdout = buf
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit:
        pass  # Every hook ends in sys.exit(0); that is normal termination.
    except Exception as exc:
        print(
            f"[posttool-dispatch] {path.name} raised {type(exc).__name__}: {exc} (skipped, failing open)",
            file=sys.stderr,
        )
        if hook_health is not None:
            hook_health.record_failure(path.name, exc, event="PostToolUse")
    finally:
        sys.stdin, sys.stdout, sys.path[:] = saved_stdin, saved_stdout, saved_path
    return buf.getvalue()


def _harvest(stdout_text: str, contexts: list[str], messages: list[str]) -> None:
    """Pull context/message content out of one hook's stdout.

    JSON envelopes contribute their fields; anything else is plain text a hook
    meant Claude to see, so it is carried through as context.
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
            # A bare {"hookSpecificOutput": {"hookEventName": ...}} is a no-op.
        else:
            contexts.append(chunk)


def main():
    try:
        payload = sys.stdin.read() if not sys.stdin.isatty() else ""
    except Exception:
        payload = ""

    try:
        tool_name = json.loads(payload).get("tool_name", "")
    except Exception:
        tool_name = ""

    only = os.environ.get("POSTTOOL_DISPATCH_ONLY")

    contexts: list[str] = []
    messages: list[str] = []

    for name, matcher in CHAIN:
        if only and name != only:
            continue
        if not only and not _matches(matcher, tool_name):
            continue
        path = HOOKS_DIR / name
        if not path.exists():
            print(f"[posttool-dispatch] missing hook {name} (skipped)", file=sys.stderr)
            continue
        _harvest(_run_hook(path, payload), contexts, messages)

    inner = {"hookEventName": "PostToolUse"}
    if contexts:
        inner["additionalContext"] = "\n".join(contexts)
    if messages:
        inner["userMessage"] = "\n".join(messages)
    print(json.dumps({"hookSpecificOutput": inner}))
    sys.exit(0)


if __name__ == "__main__":
    main()
