#!/usr/bin/env python3
# hook-version: 1.0.0
"""
PreToolUse:Bash Hook: Protected Ref Deletion Guard

Blocks deletion of protected git refs (main, master, the night-shift runner
branch, HEAD) while allowing topic branches to be deleted.

WHY THIS EXISTS
---------------
settings.json previously denied ALL remote ref deletion with three prefix rules
(`git push --delete*`, `git push -d *`, `git push origin :*`). That is blunt in
both directions:

  - Too tight: merged topic branches could not be cleaned up at all, so every
    tidy-up needed a human to run the command by hand.
  - Too loose: prefix matching only sees the spelling it was given.
    `git push --delete origin main` matches NONE of those three rules, because
    the remote and the flag are in the other order. A rule that blocks the safe
    spelling and misses the dangerous one is worse than no rule.

This hook reads the ARGUMENTS instead of the prefix, so ordering, extra flags,
`refs/heads/` qualification, and quoting cannot slip past it. settings.json
keeps narrow prefix denies for `main` as belt-and-braces: this hook fails OPEN
on a crash (as every hook here must), and a crashed guard must not silently
hand back the ability to delete main.

COVERED FORMS
-------------
  git push <remote> --delete <ref>...     (any flag/remote order)
  git push <remote> -d <ref>...
  git push <remote> :<ref>                (colon refspec)
  git branch -d/-D/--delete <branch>...
  git update-ref -d <ref>
  gh api -X DELETE .../git/refs/heads/<ref>   (the REST bypass)

Allow-through: anything targeting only unprotected refs, non-deleting commands,
and REF_DELETE_GUARD_BYPASS=1.
"""

import json
import os
import re
import shlex
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
try:
    from learning_db_v2 import record_governance_event
except Exception:  # pragma: no cover - recording is best-effort only
    record_governance_event = None
from stdin_timeout import read_stdin

_BYPASS_ENV = "REF_DELETE_GUARD_BYPASS"

# Deleting any of these is a human decision, never an agent's.
# night-shift-runner: the scheduled job reads whatever is checked out there.
_PROTECTED = {"main", "master", "head", "night-shift-runner", "gh-pages"}


def _norm(ref: str) -> str:
    """Reduce a ref to the bare branch name for comparison."""
    ref = ref.strip().strip("'\"")
    ref = re.sub(r"^\+", "", ref)          # force-push marker
    ref = re.sub(r"^refs/heads/", "", ref)
    ref = re.sub(r"^origin/", "", ref)
    return ref.strip().lower()


# Interpreters that EXECUTE a heredoc body. Their heredocs stay in scope.
_INTERPRETERS = {"bash", "sh", "zsh", "ksh", "dash", "python", "python3",
                 "node", "perl", "ruby", "eval", "source", "."}


def _strip_heredocs(command: str) -> str:
    """Remove heredoc BODIES that are data, not code.

    Found the hard way: this hook blocked a `cat > memory.md <<EOF` whose prose
    DOCUMENTED `git push --delete origin main`. The guard reads the whole Bash
    string, so text that merely mentions a deletion looked like one — the same
    whole-command trap the branch hook has.

    A heredoc fed to bash/python/etc. is still code, so those bodies are left in
    place; otherwise `bash <<EOF ... EOF` would be a one-line bypass.
    """
    out, pos = [], 0
    for m in re.finditer(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1", command):
        line_start = command.rfind("\n", 0, m.start()) + 1
        head = command[line_start : m.start()]
        toks = head.replace("|", " ").split()
        executes = any(t.rsplit("/", 1)[-1] in _INTERPRETERS for t in toks)
        term = m.group(2)
        body = re.search(rf"\n\s*{re.escape(term)}\s*$", command[m.end():], re.M)
        if not body:
            continue
        if executes:
            continue  # body is code — keep judging it
        out.append(command[pos : m.end()])
        pos = m.end() + body.end()
    out.append(command[pos:])
    return "".join(out)


def _split_segments(command: str) -> list[str]:
    """Split a compound shell command into individually-judged segments."""
    command = _strip_heredocs(command)
    return [s for s in re.split(r"&&|\|\||;|\n|\|", command) if s.strip()]


def _targets(segment: str) -> list[str]:
    """Refs this segment would DELETE. Empty list = not a deleting command."""
    try:
        argv = shlex.split(segment)
    except ValueError:
        argv = segment.split()
    if not argv:
        return []

    low = [a.lower() for a in argv]

    # gh api -X DELETE .../git/refs/heads/<ref>
    if "gh" in low and "api" in low:
        joined = " ".join(argv)
        if re.search(r"-X\s*DELETE|--method\s*DELETE", joined, re.I):
            m = re.search(r"git/refs/heads/(\S+)", joined)
            if m:
                return [m.group(1)]
            return []

    if "git" not in low:
        return []
    gi = low.index("git")
    rest = argv[gi + 1 :]
    rlow = [a.lower() for a in rest]
    # strip global options like -C <path>
    i = 0
    while i < len(rest) and rest[i].startswith("-"):
        i += 2 if rlow[i] in ("-c", "--git-dir", "--work-tree") else 1
    sub = rlow[i] if i < len(rest) else ""
    args = rest[i + 1 :]

    if sub == "push":
        deleting = any(a.lower() in ("--delete", "-d") for a in args)
        out = []
        for a in args:
            if a.startswith("-"):
                continue
            if a.startswith(":"):          # colon refspec always deletes
                out.append(a[1:])
            elif deleting:
                out.append(a)
        # the first positional after a --delete is the REMOTE, not a ref, when
        # more than one positional is present; drop it only if it looks like one
        if deleting and len(out) > 1 and out[0].lower() in ("origin", "upstream"):
            out = out[1:]
        return [o for o in out if o]

    if sub == "branch":
        if not any(a.lower() in ("-d", "-D", "--delete") or a == "-D" for a in args) and not any(
            a in ("-D", "-d") for a in args
        ):
            return []
        return [a for a in args if not a.startswith("-")]

    if sub == "update-ref":
        if "-d" in rlow:
            return [a for a in args if not a.startswith("-")]
        return []

    return []


def main() -> None:
    debug = os.environ.get("CLAUDE_HOOKS_DEBUG")
    raw = read_stdin(timeout=2)
    try:
        event = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    command = event.get("tool_input", {}).get("command", "") or ""
    if not command:
        sys.exit(0)

    if os.environ.get(_BYPASS_ENV) == "1":
        if debug:
            print("[ref-delete-guard] Bypassed via REF_DELETE_GUARD_BYPASS=1", file=sys.stderr)
        sys.exit(0)

    hits = []
    for seg in _split_segments(command):
        for ref in _targets(seg):
            if _norm(ref) in _PROTECTED:
                hits.append(ref.strip("'\""))

    if debug:
        print(f"[ref-delete-guard] protected refs targeted: {hits!r}", file=sys.stderr)

    if not hits:
        sys.exit(0)

    named = ", ".join(sorted(set(hits)))
    print(f"[ref-delete-guard] BLOCKED: refuses to delete protected ref(s): {named}", file=sys.stderr)
    if record_governance_event:
        try:
            record_governance_event(
                "policy_violation", tool_name="Bash", hook_phase="pre", severity="high", blocked=True
            )
        except Exception:
            pass  # Never let recording prevent a block
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        f"Deleting {named} is a human decision, not an agent's. "
                        "Topic branches may be deleted freely; protected refs may not. "
                        "If this is genuinely intended, run the command yourself."
                    ),
                }
            }
        )
    )
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        if os.environ.get("CLAUDE_HOOKS_DEBUG"):
            traceback.print_exc(file=sys.stderr)
        else:
            print(f"[ref-delete-guard] Error: {type(e).__name__}: {e}", file=sys.stderr)
        # A crashed hook must fail OPEN — settings.json keeps prefix denies for
        # main precisely so this failure mode is not a hole.
    finally:
        sys.exit(0)
