#!/usr/bin/env python3
"""Tests for pretool-ref-delete-guard.py.

Pins the behaviour of the protected-ref deletion guard, which replaced three
blanket prefix denies in settings.json on 2026-09-02.

Why these cases and not fewer: the rules this hook replaced were PREFIX rules,
and a prefix only matches the spelling it was given. `git push origin --delete
main` matched them; `git push --delete origin main` — the same deletion with the
flags before the remote — matched nothing at all. The old config blocked routine
cleanup and let the dangerous form through. Every ordering below exists because
a prefix rule got one of them wrong.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).parent.parent / "pretool-ref-delete-guard.py"
SETTINGS = Path.home() / ".claude" / "settings.json"


def blocks(command: str) -> bool:
    """True when the hook denies this command."""
    r = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"tool_name": "Bash", "tool_input": {"command": command}}),
        capture_output=True,
        text=True,
        timeout=20,
    )
    if not r.stdout.strip():
        return False
    out = json.loads(r.stdout)
    return out["hookSpecificOutput"]["permissionDecision"] == "deny"


PROTECTED_FORMS = [
    "git push origin --delete main",
    "git push --delete origin main",          # flags first — the old rules MISSED this
    "git push origin -d main",
    "git push -d origin main",
    "git push origin :main",
    "git push origin --delete refs/heads/main",
    "git push origin --delete master",
    "git push origin --delete night-shift-runner",
    "git push origin --delete gh-pages",
    "git branch -D main",
    "git branch --delete main",
    "git update-ref -d refs/heads/main",
    "gh api -X DELETE repos/o/r/git/refs/heads/main",
    "gh api --method DELETE repos/o/r/git/refs/heads/main",
    "cd /tmp/x && git push origin --delete main",
    "git -C /tmp/x push origin --delete main",
    "git push origin --delete feat/topic main",   # mixed: one protected ref is enough
    'git push origin --delete "main"',
]

ALLOWED_FORMS = [
    "git push origin --delete feat/topic",
    "git push origin --delete feat/a fix/b chore/c",
    "git push origin :feat/topic",
    "git push origin -d fix/topic",
    "git branch -d feat/topic",
    "git branch -D feat/topic",                # local force-delete of a TOPIC branch
    "git push origin main",                    # pushing to main is not deleting it
    "git push --force-with-lease origin feat/x",
    "git status",
    "git log --oneline main",
    "git branch --list main",
]


@pytest.mark.parametrize("cmd", PROTECTED_FORMS)
def test_protected_refs_are_blocked(cmd):
    assert blocks(cmd), f"guard let a protected-ref deletion through: {cmd}"


@pytest.mark.parametrize("cmd", ALLOWED_FORMS)
def test_topic_branches_and_reads_are_allowed(cmd):
    assert not blocks(cmd), f"guard blocked a safe command: {cmd}"


# --- heredocs -------------------------------------------------------------
# The guard reads the whole Bash string. Writing the memory file that DOCUMENTS
# this change was blocked on the day it shipped, because prose describing a
# deletion looks exactly like one. Data heredocs are stripped; heredocs piped to
# an interpreter are still code and must stay in scope, or `bash <<EOF` would be
# a one-line bypass.

DOC = "cat > notes.md <<'EOF'\nrun: git push --delete origin main\nEOF\n"
CODE = "bash <<'EOF'\ngit push origin --delete main\nEOF\n"
AFTER = "cat > notes.md <<'EOF'\nharmless\nEOF\ngit push origin --delete main\n"


def test_data_heredoc_documenting_a_deletion_is_allowed():
    assert not blocks(DOC)


def test_code_heredoc_executing_a_deletion_is_blocked():
    assert blocks(CODE), "heredoc piped to bash is code — stripping it would be a bypass"


def test_deletion_after_a_data_heredoc_is_still_blocked():
    assert blocks(AFTER)


# --- drift ----------------------------------------------------------------


def _protected_from_hook() -> set[str]:
    ns: dict = {}
    src = HOOK.read_text()
    start = src.index("_PROTECTED = {")
    end = src.index("}", start) + 1
    exec(src[start:end].replace("_PROTECTED", "P"), ns)  # noqa: S102 - literal set only
    return ns["P"]


def test_settings_prefix_denies_cover_every_protected_branch():
    """The hook is the real guard, but it FAILS OPEN on a crash.

    settings.json therefore keeps narrow prefix denies as the fallback. If a
    branch is added to the hook's _PROTECTED and not to settings, that fallback
    silently stops covering it — which is only discovered the day the hook
    breaks. HEAD is excluded: it is not a branch anyone pushes by name.
    """
    deny = set(json.loads(SETTINGS.read_text())["permissions"]["deny"])
    missing = []
    for ref in sorted(_protected_from_hook() - {"head"}):
        for form in (
            f"Bash(git push origin --delete {ref}*)",
            f"Bash(git push origin -d {ref}*)",
            f"Bash(git push origin :{ref}*)",
            f"Bash(git push --delete origin {ref}*)",
            f"Bash(git push -d origin {ref}*)",
        ):
            if form not in deny:
                missing.append(form)
    assert not missing, "hook protects refs that settings.json does not: " + ", ".join(missing)
