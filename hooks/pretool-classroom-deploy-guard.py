#!/usr/bin/env python3
# hook-version: 1.3.0
"""
PreToolUse:Bash Hook: Classroom Deploy Safety Guard

Targets Joel's most expensive, *recurring* real-world incidents (documented across
multiple memory entries): the live classroom / eduwonderlab Cloudflare site getting
clobbered or reverted. Root causes seen repeatedly:

  1. Manual `wrangler ... deploy` fighting Cloudflare's Git auto-deploy → "reverts
     to old version" (project_classroom_deploy, project_eduwonderlab_durable_updates).
  2. Generator run with `--force` stripping the hand-maintained curriculum hub
     (project_curriculum_clobber_hazard; good baseline = tag stable-baseline-2026-06-04).
  3. Pushing / deploying from the STALE EduWonderLab clone instead of the live repo
     (project_eduwonderlab_rescue, feedback_deploy_divergence: "never push the clone").

Decision policy (fail-open everywhere; only acts on actual deploy/push verbs):
  - DENY: git push OR wrangler deploy executed from a stale-clone path.

  The two former ASK confirmations (manual `wrangler deploy`, and `--force`
  generator runs in a classroom tree) were removed at Joel's request so the
  guard never prompts. Only the catastrophic stale-clone case still blocks.

  - DENY: deploy from a Cloudflare repo that has NO in-repo deploy guard,
    unless ALLOW_DEPLOY=1 (added 2026-09-02, rule 2 below).

RULE 2 — UNGUARDED REPOS
------------------------
The classroom family (neft-classroom-html-activities, nca-adaptive,
neft-math-brain, every wt-* worktree) enforces deploys through
`scripts/guard-deploy.js` + `npm run ship`, so this hook deliberately stays out
of their way — that never-prompt behaviour is Joel's recorded decision and is
NOT changed here.

Five other Cloudflare projects have `deploy` scripts and no in-repo guard at
all, so nothing stood between an agent and a live deploy:

    jewishearrings        (LIVE storefront, real customer orders)
    edupulse-gradebook
    eduwonderlab-home
    neft-school-hub-api
    neft-hub

For those five only, a deploy verb is denied unless ALLOW_DEPLOY is granted —
matching the global rule already written in ~/.claude/CLAUDE.md ("Production
deploys require ALLOW_DEPLOY=1"). This is a DENY, never an ASK, so the guard
still never prompts.

v1.3.0: ALLOW_DEPLOY is read FRESH from the settings `env` block, never from
this process's environment. Claude Code exports settings env into its own
process at startup and every child inherits it, so an os.environ check stayed
satisfied for the rest of the session after the settings entry was removed —
observed 2026-09-04, when the guard sat soft for hours after a deploy's
temporary grant was reverted. A fresh read makes authorization a current
state: add the key to deploy, remove it and the guard is hard again
immediately. A command-line prefix (`ALLOW_DEPLOY=1 npm run ...`) never
reached this process under either scheme, which is the point.

Bypass: set CLASSROOM_DEPLOY_GUARD_BYPASS=1 (whole hook), or add
"ALLOW_DEPLOY": "1" to the `env` block of ~/.claude/settings.json or
settings.local.json (rule 2 only — the documented, intended path; remove it
when the deploy is done).
"""

import json
import os
import re
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
try:
    from stdin_timeout import read_stdin
except Exception:  # pragma: no cover - lib must never break the gate

    def read_stdin(timeout: int = 2) -> str:
        return sys.stdin.read()


_BYPASS_ENV = "CLASSROOM_DEPLOY_GUARD_BYPASS"

# Paths that indicate the STALE clone — never push/deploy from here.
# The stale clone is Documents/EduWonderLab/reveal-math-activities(.icloud-old);
# Documents/EduWonderLab itself is the skill-bundle repo (a different remote)
# and must stay pushable (narrowed 2026-08-28).
_STALE_CLONE = re.compile(
    r"(documents/.*eduwonderlab/.*reveal-math-activities|/edu[-_]?clone|eduwonderlab[-_]clone)",
    re.I,
)

_WRANGLER_DEPLOY = re.compile(r"\bwrangler\b.*\b(pages\s+deploy|deploy)\b", re.I)
_GIT_PUSH = re.compile(r"\bgit\s+push\b", re.I)

# `npm run deploy`, `deploy:production`, `bun run deploy`, ... — the spelling
# actually used in these five repos' package.json scripts.
_RUN_DEPLOY = re.compile(r"\b(?:npm|pnpm|yarn|bun)\s+run\s+deploy(?::[\w.-]+)?\b", re.I)

# Cloudflare repos with deploy scripts but NO scripts/guard-deploy.js.
# Deliberately excludes the classroom family, which guards itself.
_UNGUARDED_REPOS = frozenset(
    {
        "jewishearrings",
        "edupulse-gradebook",
        "eduwonderlab-home",
        "neft-school-hub-api",
        "neft-hub",
    }
)

_ALLOW_DEPLOY_ENV = "ALLOW_DEPLOY"

_SETTINGS_FILES = (
    Path.home() / ".claude" / "settings.json",
    Path.home() / ".claude" / "settings.local.json",
)


def _allow_deploy_granted() -> bool:
    """True only if a settings file *currently* grants ALLOW_DEPLOY=1.

    Deliberately not os.environ. Claude Code exports the settings `env` block
    into its own process at startup and children inherit it, so an env check
    stays satisfied for the whole session after the settings entry is removed.
    Reading the file makes the grant live for exactly as long as it is
    written down.
    """
    for p in _SETTINGS_FILES:
        try:
            env = json.loads(p.read_text()).get("env", {})
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(env, dict) and str(env.get(_ALLOW_DEPLOY_ENV, "")) == "1":
            return True
    return False


def _workspace_repo(cwd: str) -> str:
    """Top-level workspace directory containing cwd, or '' if outside it."""
    try:
        p = Path(cwd).expanduser().resolve()
        home = Path.home().resolve()
        rel = p.relative_to(home)
    except (ValueError, OSError, RuntimeError):
        return ""
    return rel.parts[0] if rel.parts else ""


def _unguarded_target(cwd: str, command: str) -> str:
    """Name of an unguarded repo this command targets, or ''.

    Checks the resolved cwd first, then falls back to an explicit path segment
    in the command itself (`cd ~/jewishearrings && ...` that _effective_cwd
    could not parse, `--prefix`, and similar).
    """
    repo = _workspace_repo(cwd)
    if repo in _UNGUARDED_REPOS:
        return repo
    for name in _UNGUARDED_REPOS:
        # Path-segment match only: 'neft-hub' must not match 'neft-hub-api'.
        if re.search(rf"(?:^|[/\s~]){re.escape(name)}(?:/|\s|$)", command):
            return name
    return ""


def _effective_cwd(command: str, default_cwd: str | None) -> str:
    m = re.match(r'cd\s+(?:"([^"]+)"|(\S+))\s*(?:&&|;)', command.lstrip())
    if m:
        return (m.group(1) or m.group(2) or default_cwd or "").strip()
    m = re.search(r'\bgit\s+-C\s+(?:"([^"]+)"|(\S+))', command)
    if m:
        return m.group(1) or m.group(2)
    return default_cwd or ""


def _decision(kind: str, reason: str) -> None:
    print(f"[classroom-deploy-guard] {kind.upper()}: {reason}", file=sys.stderr)
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": kind,
            "permissionDecisionReason": reason,
        }
    }
    print(json.dumps(out))
    sys.exit(0)


def main() -> None:
    if os.environ.get(_BYPASS_ENV) == "1":
        sys.exit(0)

    raw = read_stdin(timeout=2)
    try:
        event = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    command = event.get("tool_input", {}).get("command", "") or ""
    if not command:
        sys.exit(0)

    cwd = _effective_cwd(
        command, event.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR")
    )
    haystack = f"{cwd}\n{command}"

    is_push = bool(_GIT_PUSH.search(command))
    is_deploy = bool(_WRANGLER_DEPLOY.search(command)) or bool(
        _RUN_DEPLOY.search(command)
    )

    # 1. Catastrophic: push/deploy from the stale clone.
    if (is_push or is_deploy) and _STALE_CLONE.search(haystack):
        _decision(
            "deny",
            "Refusing to push/deploy from what looks like the STALE EduWonderLab clone. "
            "Per feedback_deploy_divergence: never push the clone — port changes into the LIVE "
            "neft-classroom repo and deploy from there. Override with CLASSROOM_DEPLOY_GUARD_BYPASS=1 "
            "only if you've confirmed this is the live repo.",
        )

    # 2. Deploy from a Cloudflare repo with no in-repo guard of its own.
    #    The classroom family is excluded by construction (see _UNGUARDED_REPOS).
    if is_deploy and not _allow_deploy_granted():
        target = _unguarded_target(cwd, command)
        if target:
            live = (
                " This is a LIVE storefront with real customer orders."
                if target == "jewishearrings"
                else ""
            )
            _decision(
                "deny",
                f"Deploying {target} requires explicit authorization.{live} "
                f"{target} has no scripts/guard-deploy.js, so nothing else gates this. "
                "Per ~/.claude/CLAUDE.md, production deploys require ALLOW_DEPLOY=1. "
                'A command prefix cannot grant it — add "ALLOW_DEPLOY": "1" to the env '
                "block of ~/.claude/settings.json (Joel's call, not the agent's), deploy, "
                "then remove it. The grant is live only while it is written down.",
            )

    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001 - a crashed gate must fail OPEN
        if os.environ.get("CLAUDE_HOOKS_DEBUG"):
            traceback.print_exc(file=sys.stderr)
        else:
            print(
                f"[classroom-deploy-guard] Error: {type(e).__name__}: {e}",
                file=sys.stderr,
            )
    finally:
        sys.exit(0)
