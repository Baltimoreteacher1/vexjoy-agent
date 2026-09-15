#!/usr/bin/env python3
# hook-version: 1.0.0
"""SessionStart: verify every wired hook is still loadable, and surface failures.

The gap this closes: this rig wires ~56 hook entries and keeps exactly one log
file. Nothing detects a hook that has silently stopped working. Worse, several
hooks are *supposed* to produce nothing most of the time, so an empty output
directory is indistinguishable from a broken hook without reading the source.
That ambiguity has already cost a debugging session once.

Three complementary checks, all cheap:

  1. Static - for every hook command in settings.json, confirm the script exists
     and still compiles. This catches the two failure modes that actually happen
     here: a branch switch removing a script that settings.json still references
     (phantom reference), and an edit that leaves a syntax error. Uses
     py_compile against __pycache__, so repeat runs are nearly free.

  2. Drift - compare each wired hook against its claude-code-toolkit copy. Sync
     overwrites ~/.claude/hooks from that repo whenever a session starts with the
     repo as cwd, so a live hook that has drifted ahead of its repo copy is a
     pending silent revert. On 2026-09-15 twelve hooks were in exactly that
     state, including the graduation fix in error-learner.py.

  3. Runtime - replay whatever the dispatchers recorded in hook-health.jsonl.
     Those are real exceptions from real tool calls that the dispatchers
     swallowed to fail open. See lib/hook_health.py.

Deliberately does NOT smoke-run hooks with synthetic payloads. Many of them
write to databases, archive transcripts, or back up files; invoking them with
fake input to check liveness would corrupt the very telemetry this rig collects.
Static validity plus real runtime failures covers the problem without that risk.

Always exits 0. A health check that blocks the session is a worse bug than the
ones it looks for.
"""

import json
import py_compile
import re
import sys
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(HOOKS_DIR / "lib"))

HOME = Path.home()
SETTINGS = HOME / ".claude" / "settings.json"

# sync-to-user-claude.py overwrites ~/.claude/hooks from this repo whenever a
# session starts with the repo as cwd. So a live hook that has drifted ahead of
# its repo copy is a pending silent revert, not a harmless difference.
TOOLKIT_HOOKS = HOME / "claude-code-toolkit" / "hooks"

# Pull the script path out of a hook command line, e.g.
#   python3 "$HOME/.claude/hooks/foo.py"   ->  ~/.claude/hooks/foo.py
SCRIPT_RE = re.compile(r'["\']?(\$HOME|~|/[^\s"\']*)?[^\s"\']*?([\w.-]+\.py)["\']?')


def _iter_hook_commands(settings: dict):
    for event, groups in (settings.get("hooks") or {}).items():
        for group in groups:
            for hook in group.get("hooks") or []:
                cmd = hook.get("command") or ""
                if cmd:
                    yield event, cmd


def _resolve(cmd: str) -> Path | None:
    """Best-effort: map a hook command to the .py file it runs."""
    match = SCRIPT_RE.search(cmd)
    if not match:
        return None
    raw = cmd[match.start() : match.end()].strip("\"'")
    raw = raw.replace("$HOME", str(HOME)).replace("~", str(HOME))
    # Commands are usually `python3 "<path>"`; take the last path-looking token.
    for token in reversed(raw.split()):
        token = token.strip("\"'")
        if token.endswith(".py"):
            return Path(token)
    return None


def check_static() -> tuple[list[str], set[Path]]:
    """Return (problems, the set of wired script paths)."""
    problems: list[str] = []
    try:
        settings = json.loads(SETTINGS.read_text())
    except Exception as exc:
        return [f"settings.json unreadable: {type(exc).__name__}: {exc}"], set()

    seen: set[Path] = set()
    for event, cmd in _iter_hook_commands(settings):
        path = _resolve(cmd)
        if path is None:
            continue  # Non-Python hook (binaries like headroom/rtk); nothing to compile.
        if path in seen:
            continue
        seen.add(path)

        if not path.exists():
            problems.append(f"{event}: {path.name} is wired but MISSING from disk")
            continue
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            first = str(exc).strip().splitlines()[0][:160]
            problems.append(f"{event}: {path.name} FAILS TO COMPILE - {first}")
        except Exception:
            pass  # Unwritable __pycache__ etc. is not a hook defect.

    return problems, seen


def check_drift(wired: set[Path]) -> list[str]:
    """Report wired hooks whose live copy differs from the toolkit repo copy.

    Only wired hooks are reported. An unwired script that differs changes no
    behaviour, and listing those would bury the signal in noise.
    """
    if not TOOLKIT_HOOKS.is_dir():
        return []

    problems = []
    for live_path in sorted(wired):
        if live_path.parent != HOME / ".claude" / "hooks":
            continue
        repo_path = TOOLKIT_HOOKS / live_path.name
        if not repo_path.exists():
            continue  # Global-only hook; sync preserves these.
        try:
            if live_path.read_bytes() != repo_path.read_bytes():
                problems.append(
                    f"{live_path.name} differs from the toolkit repo copy - "
                    f"a session started in claude-code-toolkit would overwrite the live version"
                )
        except Exception:
            pass
    return problems


def check_runtime() -> list[str]:
    try:
        import hook_health
    except Exception:
        return []

    failures = hook_health.read_failures()
    if not failures:
        return []

    counts: dict[str, dict] = {}
    for entry in failures:
        name = entry.get("hook", "?")
        slot = counts.setdefault(name, {"n": 0, "error": entry.get("error", "")})
        slot["n"] += 1
        slot["error"] = entry.get("error", slot["error"])

    out = []
    for name, slot in sorted(counts.items(), key=lambda kv: -kv[1]["n"]):
        out.append(f"{name} raised {slot['n']}x (latest: {slot['error'][:160]})")

    hook_health.clear()  # Reported once; do not nag every session.
    return out


def main() -> None:
    try:
        static_problems, wired = check_static()
        drift_problems = check_drift(wired)
        runtime_problems = check_runtime()
    except Exception:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart"}}))
        sys.exit(0)

    if not static_problems and not drift_problems and not runtime_problems:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart"}}))
        sys.exit(0)

    lines = [f"[hook-health] {len(wired)} wired hook scripts checked."]
    if static_problems:
        lines.append("Broken wiring:")
        lines += [f"  - {p}" for p in static_problems]
    if drift_problems:
        lines.append("Live/repo drift (pending silent revert):")
        lines += [f"  - {p}" for p in drift_problems]
    if runtime_problems:
        lines.append("Hooks that raised since the last report (dispatcher failed open):")
        lines += [f"  - {p}" for p in runtime_problems]

    message = "\n".join(lines)
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": message,
                    "userMessage": message,
                }
            }
        )
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
