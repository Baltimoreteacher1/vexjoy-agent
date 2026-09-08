#!/usr/bin/env python3
# hook-version: 1.0.0
"""
PreToolUse:Bash Hook: Git Stray-Ref / macOS Duplicate-File Detector

Recurring documented failure: macOS/Finder/iCloud creates " 2"-suffixed duplicate
files inside .git/ (e.g. `.git/refs/stash 2`, `packed-refs 2`). These silently break
`git fetch`/`pull`/`push` ("fix stray .git/refs/stash 2 to unblock fetch" —
project_axiom_city_novels). Same artifact also spawns "conflicted copy" dupes.

Before any git fetch/pull/push, this scans the effective repo's .git/ for these
corruption artifacts and, if found, emits a WARNING with the exact cleanup command.

It is WARN-ONLY and NON-BLOCKING — it never deletes (per the no-delete-without-
explicit-request safety rule) and never blocks the git command. Fail-open.
"""

import json
import os
import re
import subprocess
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
try:
    from stdin_timeout import read_stdin
except Exception:  # pragma: no cover

    def read_stdin(timeout: int = 2) -> str:
        return sys.stdin.read()


_GIT_NET_OP = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?(?:fetch|pull|push)\b", re.I)
# macOS dup artifacts: "name 2", "name 2.ext", or "... (conflicted copy ...)".
_DUP = re.compile(r"( \d+)(\.\w+)?$|conflicted copy", re.I)


def _effective_cwd(command: str, default_cwd: str | None) -> str:
    m = re.match(r'cd\s+(?:"([^"]+)"|(\S+))\s*(?:&&|;)', command.lstrip())
    if m:
        return (m.group(1) or m.group(2) or default_cwd or "").strip()
    m = re.search(r'\bgit\s+-C\s+(?:"([^"]+)"|(\S+))', command)
    if m:
        return m.group(1) or m.group(2)
    return default_cwd or ""


def _git_dir(cwd: str) -> Path | None:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=cwd or None,
        )
        if r.returncode == 0 and r.stdout.strip():
            gd = Path(r.stdout.strip())
            return gd if gd.is_absolute() else Path(cwd or ".") / gd
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None


def _find_dups(git_dir: Path) -> list[str]:
    hits: list[str] = []
    # Only scan git-internal areas where dupes actually break operations.
    scan_roots = [git_dir / "refs", git_dir]
    for root in scan_roots:
        try:
            if root == git_dir:
                # top-level files only (packed-refs 2, HEAD 2, config 2)
                children = [p for p in root.iterdir() if p.is_file()]
            else:
                children = (
                    [p for p in root.rglob("*") if p.is_file()] if root.exists() else []
                )
        except OSError:
            continue
        for p in children:
            if _DUP.search(p.name):
                hits.append(str(p))
    return sorted(set(hits))


def main() -> None:
    raw = read_stdin(timeout=2)
    try:
        event = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    command = event.get("tool_input", {}).get("command", "") or ""
    if not _GIT_NET_OP.search(command):
        sys.exit(0)

    cwd = _effective_cwd(
        command, event.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR")
    )
    git_dir = _git_dir(cwd)
    if git_dir is None:
        sys.exit(0)

    dups = _find_dups(git_dir)
    if not dups:
        sys.exit(0)

    listing = "\n".join(f"  - {d}" for d in dups[:10])
    quoted = " ".join(f'"{d}"' for d in dups[:10])
    print(
        "[git-stray-ref-detector] WARNING: macOS duplicate file(s) found inside .git/ — "
        "these silently break git fetch/pull/push:\n"
        f"{listing}\n"
        f"  Fix (review first, then): trash {quoted}\n"
        "  Not auto-deleted (no-delete safety rule). See project_axiom_city_novels.",
        file=sys.stderr,
    )
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001 — must fail OPEN
        if os.environ.get("CLAUDE_HOOKS_DEBUG"):
            traceback.print_exc(file=sys.stderr)
        else:
            print(
                f"[git-stray-ref-detector] Error: {type(e).__name__}: {e}",
                file=sys.stderr,
            )
    finally:
        sys.exit(0)
