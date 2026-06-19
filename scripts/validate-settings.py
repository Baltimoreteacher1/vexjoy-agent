#!/usr/bin/env python3
"""Validate .claude/settings.json structure and hook registration.

Checks:
- Valid JSON
- Every hook has required fields (type, command)
- Every hook has a timeout
- Every hook command references an existing file
- No duplicate hook registrations
- Matcher fields use valid tool names

Usage:
    python3 scripts/validate-settings.py [--settings PATH]
"""

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SETTINGS = REPO_ROOT / ".claude" / "settings.json"

VALID_EVENTS = {
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "PreCompact",
    "PostCompact",
    "TaskCompleted",
    "SubagentStop",
    "Stop",
    "StopFailure",
}

VALID_TOOL_NAMES = {
    "Bash",
    "Read",
    "Write",
    "Edit",
    "Glob",
    "Grep",
    "Agent",
    "Skill",
    "mcp__",
}

MAX_TIMEOUT_MS = 10000
REQUIRED_HOOK_FIELDS = {"type", "command"}


def validate(settings_path: Path) -> list[str]:
    errors: list[str] = []
    warnings: list[str] = []

    if not settings_path.exists():
        errors.append(f"Settings file not found: {settings_path}")
        return errors

    try:
        data = json.loads(settings_path.read_text())
    except json.JSONDecodeError as e:
        errors.append(f"Invalid JSON: {e}")
        return errors

    hooks_config = data.get("hooks", {})
    if not isinstance(hooks_config, dict):
        errors.append("'hooks' must be an object")
        return errors

    seen_commands: dict[str, list[str]] = {}

    for event, blocks in hooks_config.items():
        if event not in VALID_EVENTS:
            errors.append(f"Unknown event type: {event}")

        if not isinstance(blocks, list):
            errors.append(f"{event}: blocks must be an array")
            continue

        for bi, block in enumerate(blocks):
            matcher = block.get("matcher", "(all)")

            if "matcher" in block:
                parts = block["matcher"].split("|")
                for part in parts:
                    if part not in VALID_TOOL_NAMES and not any(part.startswith(v) for v in VALID_TOOL_NAMES):
                        warnings.append(f"{event}[{bi}]: unknown tool in matcher: {part}")

            for hi, hook in enumerate(block.get("hooks", [])):
                loc = f"{event}[{bi}].hooks[{hi}] (matcher={matcher})"

                for field in REQUIRED_HOOK_FIELDS:
                    if field not in hook:
                        errors.append(f"{loc}: missing required field '{field}'")

                if "timeout" not in hook:
                    errors.append(f"{loc}: missing timeout")
                elif hook["timeout"] > MAX_TIMEOUT_MS:
                    warnings.append(f"{loc}: timeout {hook['timeout']}ms exceeds {MAX_TIMEOUT_MS}ms")

                cmd = hook.get("command", "")
                m = re.search(r'hooks/([^"]+\.py)', cmd)
                if m:
                    hook_file = m.group(1)
                    hook_path = REPO_ROOT / "hooks" / hook_file
                    if not hook_path.exists():
                        errors.append(f"{loc}: hook file not found: hooks/{hook_file}")

                    key = f"{event}:{hook_file}"
                    seen_commands.setdefault(key, []).append(loc)

    for key, locations in seen_commands.items():
        if len(locations) > 1:
            warnings.append(f"Duplicate registration: {key} registered {len(locations)} times")

    return errors + [f"WARNING: {w}" for w in warnings]


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate .claude/settings.json")
    parser.add_argument("--settings", type=Path, default=DEFAULT_SETTINGS)
    args = parser.parse_args()

    issues = validate(args.settings)

    if not issues:
        print("PASS: settings.json is valid (all hooks have type, command, timeout; all files exist)")
        return 0

    errors = [i for i in issues if not i.startswith("WARNING:")]
    warnings = [i for i in issues if i.startswith("WARNING:")]

    if errors:
        print(f"FAIL: {len(errors)} error(s)")
        for e in errors:
            print(f"  ERROR: {e}")

    if warnings:
        print(f"WARNINGS: {len(warnings)}")
        for w in warnings:
            print(f"  {w}")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
