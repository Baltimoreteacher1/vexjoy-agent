#!/usr/bin/env python3
# hook-version: 1.0.0
"""
PostToolUse Hook: Error Learning System with Automatic Feedback

Detects errors from tool executions and learns from patterns.
Uses SQLite database for persistent cross-session learning.
AUTOMATICALLY tracks fix outcomes for reinforcement learning.

Design Principles:
- SILENT when no errors detected (no noise)
- Non-blocking (always exits 0)
- Fast execution (<50ms target)
- SQLite for robust storage
- AUTOMATIC feedback loop (no manual intervention)
"""

import json
import os
import re
import sys
from pathlib import Path

# Add lib directory to path for imports
sys.path.insert(0, str(Path(__file__).parent / "lib"))

from feedback_tracker import check_pending_feedback, set_pending_feedback
from learning_db_v2 import (
    DEFAULT_FIX_ACTIONS,
    boost_confidence,
    classify_error,
    decay_confidence,
    generate_signature,
    lookup_error_solution,
    record_learning,
    sanitize_for_context,
)
from stdin_timeout import read_stdin

# Marks an error that has been seen but never successfully fixed. Kept as a
# stable sentinel so the graduation proposer can exclude these rows: an entry
# with no confirmed fix carries no knowledge and must never be promoted into
# ~/.claude/rules/, no matter how often the error recurs.
NO_SOLUTION_MARKER = "(no confirmed fix yet)"

# Lines that carry the actual diagnosis, most specific first.
_SIGNAL_PATTERNS = [
    r"\b[A-Za-z_]*Error\b",
    r"\bERR_[A-Z_]+\b",
    r"\bException\b",
    r"\bfatal:",
    r"\bno such file or directory\b",
    r"\bcommand not found\b",
    r"\bpermission denied\b",
    r"\bcannot find\b",
    r"\bnot found\b",
    r"\bfailed\b",
    r"\brefused\b",
    r"\btimed? ?out\b",
    r"\bundefined\b",
]

# Decorative / echoed shell output. A Bash failure's stderr is whatever the whole
# command emitted, so a compound command's `echo "=== step ==="` banners land in
# the error text and, being first, used to be what got stored.
_NOISE_LINE = re.compile(r"^\s*(={2,}.*|-{2,}|\*{2,}|#.*)\s*$")

_EXIT_CODE = re.compile(r"^\s*Exit code (\d+)", re.IGNORECASE)


def extract_error_signal(message: str, max_len: int = 220) -> str:
    """Pull the diagnostic line out of a raw error dump.

    The stored value used to be `message[:200]` — the FIRST 200 characters of
    combined output. For a compound Bash command that is usually banner text,
    so rows read "Exit code 1 === crontab === (no matching cron entries)" and
    the real diagnosis, further down, was truncated away. This keeps the exit
    code (cheap, useful) and pairs it with the line that actually diagnoses.
    """
    if not message:
        return ""

    raw_lines = message.splitlines()
    exit_code = ""
    for line in raw_lines[:2]:
        m = _EXIT_CODE.match(line)
        if m:
            exit_code = f"Exit code {m.group(1)}"
            break

    lines = [ln.strip() for ln in raw_lines if ln.strip() and not _NOISE_LINE.match(ln) and not _EXIT_CODE.match(ln)]
    if not lines:
        return (exit_code or message.strip())[:max_len]

    signal = ""
    # A Python traceback's final line is the exception; the frames above are noise.
    if any("Traceback (most recent call last)" in ln for ln in lines):
        signal = lines[-1]
    else:
        for pattern in _SIGNAL_PATTERNS:
            hit = next((ln for ln in lines if re.search(pattern, ln, re.IGNORECASE)), None)
            if hit:
                signal = hit
                break
        if not signal:
            signal = lines[0]

    combined = f"{exit_code}: {signal}" if exit_code else signal
    return combined[:max_len]


def process_automatic_feedback(current_error: str | None) -> None:
    """Process automatic feedback from previous fix suggestion.

    Uses learning_db_v2 boost/decay instead of direct SQL.
    """
    feedback = check_pending_feedback(current_error)
    if not feedback:
        return

    # The feedback tracker stores the error_type as topic and signature as key
    error_type = feedback.get("error_type", "unknown")
    signature = feedback["signature"]

    if feedback["success"]:
        new_confidence = boost_confidence(error_type, signature, 0.15)
        status = "✓"
    else:
        new_confidence = decay_confidence(error_type, signature, 0.1)
        status = "✗"

    if new_confidence > 0:
        print(f"[auto-feedback] {status} {feedback['reason']}")
        print(f"[auto-feedback] confidence → {new_confidence:.2f}")


def normalize_result(event: dict) -> tuple[str | None, str]:
    """Flatten either payload shape into (direct_error, output_text).

    Verified against live 2.1.236 hook captures:
      PostToolUseFailure -> top-level "error": str  (no tool_response)
      PostToolUse        -> "tool_response": {"stdout","stderr",...}, success only

    The "tool_result" key this hook was originally written against does not
    exist in any event, which is why it never recorded a real error. It is
    still read last, for forward/backward compatibility.
    """
    direct = event.get("error")
    if isinstance(direct, str) and direct.strip():
        return direct, direct

    result = event.get("tool_response")
    if result is None:
        result = event.get("tool_result", {})

    if isinstance(result, str):
        return None, result
    if not isinstance(result, dict):
        return None, ""

    if "error" in result:
        return str(result["error"]), str(result["error"])

    parts = [result.get("stdout"), result.get("stderr"), result.get("output")]
    text = "\n".join(p for p in parts if isinstance(p, str) and p)
    if not text:
        for key in ("content", "message", "result"):
            value = result.get(key)
            if isinstance(value, str) and value:
                text = value
                break
    return None, text


def detect_error(event: dict) -> tuple[bool, str]:
    """Detect if tool execution had an error.

    Returns:
        Tuple of (has_error, error_message)
    """
    # PostToolUse fires on SUCCESS only. Keyword-scanning the stdout of a
    # command that succeeded is how a `grep -c timeout` or a build log that
    # merely mentions "error" gets recorded as a failure — the scan below is
    # for failure events, where the text is genuinely an error message.
    if event.get("hook_event_name") == "PostToolUse":
        return False, ""

    direct_error, output = normalize_result(event)

    # Direct error field
    if direct_error:
        return True, direct_error

    # Check for error in output
    if isinstance(output, str):
        output_lower = output.lower()

        # Error indicators that match our ERROR_TYPES patterns
        error_indicators = [
            "error",
            "failed",
            "permission denied",
            "access denied",
            "not found",
            "no such file",
            "cannot find",
            "does not exist",
            "syntax error",
            "unexpected token",
            "type error",
            "import error",
            "module not found",
            "no module named",
            "timeout",
            "timed out",
            "connection refused",
            "traceback",
            "exception",
        ]

        if any(indicator in output_lower for indicator in error_indicators):
            # Avoid false positives for success messages
            if "0 errors" not in output_lower and "no errors" not in output_lower:
                # Avoid false positives for benign text patterns
                false_positive_phrases = [
                    "error handling",
                    "error handler",
                    "failed over",
                    "failover",
                    "not found in cache",
                ]
                if any(phrase in output_lower for phrase in false_positive_phrases):
                    return False, ""
                # Avoid false positives for error keywords inside code identifiers
                # e.g., ErrorType, handle_error, on_error, etc.
                import re as _re

                if _re.search(
                    r"[A-Z][a-z]*[Ee]rror[A-Z]|[a-z_][Ee]rror[A-Za-z_]|[Hh]andle[_]?[Ee]rror",
                    output,
                ):
                    # Only suppress if ALL error indicators are inside identifiers
                    plain_indicators = [
                        "failed",
                        "permission denied",
                        "access denied",
                        "no such file",
                        "cannot find",
                        "does not exist",
                        "syntax error",
                        "unexpected token",
                        "module not found",
                        "no module named",
                        "traceback",
                        "exception",
                    ]
                    if not any(indicator in output_lower for indicator in plain_indicators):
                        return False, ""
                return True, output

    # Check for non-zero exit code mention in Bash tool
    tool_name = event.get("tool_name", "")
    if tool_name == "Bash" and isinstance(output, str):
        if "exit code" in output.lower() and "exit code 0" not in output.lower():
            return True, output

    return False, ""


def main():
    """Process PostToolUse events with automatic feedback loop.

    Flow:
    1. Check if previous fix suggestion worked (automatic feedback)
    2. Detect errors in current tool result
    3. Look up or record patterns
    4. Set pending feedback for next iteration
    """
    try:
        event_data = read_stdin(timeout=2)
        if not event_data:
            return

        event = json.loads(event_data)

        # Only process tool-completion events. PostToolUse fires on success
        # only; failed tool calls arrive as PostToolUseFailure and are the
        # events this hook actually exists to learn from.
        event_type = event.get("hook_event_name") or event.get("type", "")
        if event_type not in ("PostToolUse", "PostToolUseFailure"):
            return

        # Check for errors in current result
        has_error, error_message = detect_error(event)

        # AUTOMATIC FEEDBACK: Check if previous fix worked
        # This happens on EVERY PostToolUse - if no pending feedback, it's a no-op
        process_automatic_feedback(error_message if has_error else None)

        # If no error now, we're done (feedback already processed above)
        if not has_error:
            return

        # Get context
        tool_name = event.get("tool_name", "unknown")
        agent_type = event.get("agent_type", "")
        cwd = event.get("cwd", str(Path.cwd()))

        # Build source_detail with agent attribution
        source_detail = f"{tool_name}:{agent_type}" if agent_type else tool_name

        # Classify and generate signature
        error_type = classify_error(error_message)
        signature = generate_signature(error_message, error_type)

        # Sanitize before storing or replaying in context
        error_message = sanitize_for_context(error_message)

        # Check for existing solution in unified DB
        existing = lookup_error_solution(error_message)
        if existing and existing.get("value"):
            fix_type = existing.get("fix_type", "manual")
            fix_action = existing.get("fix_action", "")
            solution = existing["value"]

            # Emit structured fix instruction based on type
            if fix_type == "auto" and fix_action:
                print(f"[auto-fix] type={fix_type} action={fix_action}")
                print(f"[auto-fix] solution: {solution}")
            elif fix_type == "skill" and fix_action:
                print(f"[fix-with-skill] {fix_action}")
                print(f"[fix-with-skill] reason: {solution}")
            elif fix_type == "agent" and fix_action:
                print(f"[fix-with-agent] {fix_action}")
                print(f"[fix-with-agent] reason: {solution}")
            else:
                print(f"[learned-solution] {solution}")

            set_pending_feedback(
                signature=signature,
                error_type=error_type,
                fix_action=fix_action or fix_type,
                original_error=error_message,
            )

            # Re-record to boost confidence
            record_learning(
                topic=error_type,
                key=signature,
                value=f"{extract_error_signal(error_message)} → {solution}",
                category="error",
                source="hook:error-learner",
                source_detail=source_detail,
                project_path=cwd,
                error_signature=signature,
                error_type=error_type,
                fix_type=fix_type,
                fix_action=fix_action,
            )
        else:
            # New error — record with default fix action
            fix_info = DEFAULT_FIX_ACTIONS.get(error_type, {"fix_type": "manual", "fix_action": "investigate"})
            fix_type = fix_info["fix_type"]
            fix_action = fix_info["fix_action"]
            # Do NOT fabricate a solution here. This branch means "first time we
            # have seen this error and nobody has fixed it yet" — there is no
            # knowledge to record. The previous value, f"Fix {error_type} error
            # in {tool_name}", produced rows reading
            #   "Exit code 1 ... -> Fix unknown error in Bash"
            # i.e. a raw stdout fragment joined to a tautology. Those rows are
            # why the learning DB held 100 entries and none were worth
            # graduating. Store the error alone, tagged as unsolved; the
            # feedback loop (process_automatic_feedback) fills in a real
            # solution if a later fix actually works.
            solution = NO_SOLUTION_MARKER

            print(f"[new-error] {error_type}: {error_message[:100]}")
            if fix_type == "auto":
                print(f"[new-error] suggested action: {fix_action}")
            elif fix_type == "skill":
                print(f"[new-error] suggested skill: {fix_action}")
            else:
                print(f"[new-error] suggestion: {solution}")

            set_pending_feedback(
                signature=signature,
                error_type=error_type,
                fix_action=fix_action,
                original_error=error_message,
            )

            record_learning(
                topic=error_type,
                key=signature,
                value=f"{extract_error_signal(error_message)} → {solution}",
                category="error",
                source="hook:error-learner",
                source_detail=source_detail,
                project_path=cwd,
                error_signature=signature,
                error_type=error_type,
                fix_type=fix_type,
                fix_action=fix_action,
            )

    except Exception as e:
        if os.environ.get("CLAUDE_HOOKS_DEBUG"):
            import traceback

            print(f"[error-learner] HOOK-ERROR: {type(e).__name__}: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
    finally:
        sys.exit(0)  # Never block


if __name__ == "__main__":
    main()
