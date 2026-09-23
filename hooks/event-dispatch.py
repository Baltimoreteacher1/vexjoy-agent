#!/usr/bin/env python3
# hook-version: 1.0.0
"""Dispatcher for the context-only hook events, one interpreter per event.

Why: the same problem pretool-dispatch.py and posttool-dispatch.py already
solved, on the three events that were still spending a fresh Python interpreter
per hook. Measured on this machine:

  SessionStart       10 processes  ~490ms   every startup, resume, clear, compact
  UserPromptSubmit    5 processes  ~230ms   before every single prompt
  Stop                5 processes  ~200ms   after every single turn

The hooks themselves are cheap. The process starts were the cost, and on
UserPromptSubmit and Stop it was being paid twice per turn.

SessionStart's cost is also paid more often than the old configuration implied.
Its ten entries each carried `once: true`, but Claude Code 2.1.267 has no
implementation for a `once` field on a settings.json hook entry - grep the
binary and it appears only in unrelated places (EventEmitter.once, a
firedOnceKeys latch for UI notices). So that chain ran on every SessionStart,
not once per session.

These three events share one contract, which is why they share one dispatcher:

  - No hook in any of these chains makes a permission decision or blocks - they
    are all context injectors and recorders (verified across all twenty). So
    there is no first-decision-wins short circuit: every hook in the chain runs,
    always. That is what separates this from pretool-dispatch.py.
  - Because they all run, their stdout has to be merged. Sequentially, Claude
    Code parsed each hook's stdout independently; here it sees one stream. So
    JSON envelopes contribute their additionalContext and userMessage, plain
    text contributes itself, and the result is emitted as a single well-formed
    envelope carrying the event's own hookEventName. Concatenating raw JSON
    objects would produce output Claude Code cannot parse.
  - Order is preserved. The injected context is order-sensitive: the operator
    profile, team config and learned-pattern blocks are read as one sequence.
  - Fail OPEN, same as the sibling dispatchers. A hook that raises is logged to
    stderr, recorded for the health report, and skipped. A dispatcher that
    failed closed would turn any bug here into a session that cannot start or a
    turn that cannot end.

Deliberately NOT in the SessionStart chain: settings-pin-guard.py and
context-window-guard.py. Both are curated global-only hooks with no copy in the
toolkit repo, and this dispatcher is repo-owned, so a sync to a checkout without
those files would silently stop running them - and settings-pin-guard is what
heals settings self-mutation. They stay registered as their own settings.json
group. PostToolUseFailure is left alone for the same mixed-ownership reason,
plus it only fires when a tool call fails.

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

# Each chain is the exact order those hooks fired as separate settings.json
# entries. sync-to-user-claude stays first in SessionStart: it rewrites
# ~/.claude/settings.json, and later hooks read files it may have just
# refreshed.
CHAINS: dict[str, list[str]] = {
    "SessionStart": [
        "sync-to-user-claude.py",
        "afk-mode.py",
        "session-context.py",
        "fish-shell-detector.py",
        "operator-context-detector.py",
        "retro-knowledge-injector.py",
        "kairos-briefing-injector.py",
        "rules-distill-injector.py",
        "team-config-loader.py",
        "hook-health-report.py",
    ],
    "UserPromptSubmit": [
        "instruction-reminder.py",
        "pipeline-context-detector.py",
        "user-correction-capture.py",
        "auto-plan-detector.py",
        "codex-auto-review.py",
    ],
    "Stop": [
        "session-summary.py",
        "confidence-decay.py",
        "session-learning-recorder.py",
        "knowledge-graduation-proposer.py",
        "rules-distill-trigger.py",
    ],
}


def _run_hook(path: Path, payload: str, event: str) -> str:
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
            f"[event-dispatch] {path.name} raised {type(exc).__name__}: {exc} (skipped, failing open)",
            file=sys.stderr,
        )
        if hook_health is not None:
            hook_health.record_failure(path.name, exc, event=event)
    finally:
        sys.stdin, sys.stdout, sys.path[:] = saved_stdin, saved_stdout, saved_path
    return buf.getvalue()


def _harvest(stdout_text: str, contexts: list[str], messages: list[str]) -> None:
    """Pull context/message content out of one hook's stdout.

    JSON envelopes contribute their fields; anything else is plain text a hook
    meant Claude to see. A bare {"hookSpecificOutput": {"hookEventName": ...}}
    is a no-op and contributes nothing.

    Runs of plain text are kept together rather than split per line, so
    multi-line injected blocks survive intact.
    """
    text = stdout_text.strip()
    if not text:
        return
    plain: list[str] = []
    for chunk in text.split("\n"):
        stripped = chunk.strip()
        if stripped.startswith("{"):
            try:
                obj = json.loads(stripped)
            except Exception:
                plain.append(chunk)
                continue
            if plain:
                if "\n".join(plain).strip():
                    contexts.append("\n".join(plain).strip())
                plain = []
            inner = obj.get("hookSpecificOutput") or {}
            if inner.get("additionalContext"):
                contexts.append(inner["additionalContext"])
            if inner.get("userMessage"):
                messages.append(inner["userMessage"])
        else:
            plain.append(chunk)
    if plain and "\n".join(plain).strip():
        contexts.append("\n".join(plain).strip())


def main():
    try:
        payload = sys.stdin.read() if not sys.stdin.isatty() else ""
    except Exception:
        payload = ""

    try:
        event = json.loads(payload).get("hook_event_name", "")
    except Exception:
        event = ""

    chain = CHAINS.get(event)
    if chain is None:
        # An event this dispatcher does not own. Emit nothing and succeed rather
        # than guessing a chain.
        print(f"[event-dispatch] no chain for event {event!r} (nothing to do)", file=sys.stderr)
        sys.exit(0)

    only = os.environ.get("EVENT_DISPATCH_ONLY")

    contexts: list[str] = []
    messages: list[str] = []

    for name in chain:
        if only and name != only:
            continue
        path = HOOKS_DIR / name
        if not path.exists():
            print(f"[event-dispatch] missing hook {name} (skipped)", file=sys.stderr)
            continue
        _harvest(_run_hook(path, payload, event), contexts, messages)

    inner = {"hookEventName": event}
    if contexts:
        inner["additionalContext"] = "\n".join(contexts)
    if messages:
        inner["userMessage"] = "\n".join(messages)
    print(json.dumps({"hookSpecificOutput": inner}))
    sys.exit(0)


if __name__ == "__main__":
    main()
