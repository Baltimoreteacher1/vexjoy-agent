#!/usr/bin/env python3
"""Tests sync_settings() hook-block merging.

The repo's hook list is authoritative for hooks the repo manages, but the sync
must not drop curated global-only hooks whose script files exist on disk
(settings-pin-guard, context-window-guard, …). The original full-replace was
there to remove *phantom* hooks — entries whose script file no longer exists
after a branch switch — so the merge keeps that removal by its real criterion:
a global-only hook survives iff every script path in its command exists.

Run with: python3 -m pytest hooks/tests/test_sync_settings.py -v
"""

import importlib.util
from pathlib import Path

HOOK_PATH = Path(__file__).resolve().parents[1] / "sync-to-user-claude.py"

spec = importlib.util.spec_from_file_location("sync_to_user_claude", HOOK_PATH)
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


def _hook(command: str) -> dict:
    return {"type": "command", "command": command}


def _group(*commands: str) -> dict:
    return {"hooks": [_hook(c) for c in commands]}


def _commands(settings: dict, event: str) -> list[str]:
    return [h["command"] for grp in settings.get("hooks", {}).get(event, []) for h in grp.get("hooks", [])]


def _make_home(tmp_path: Path, *scripts: str) -> Path:
    hooks_dir = tmp_path / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    for name in scripts:
        (hooks_dir / name).write_text("# stub\n")
    return tmp_path


class TestGlobalOnlyHookPreservation:
    def test_global_only_hook_with_existing_script_is_preserved(self, tmp_path: Path) -> None:
        home = _make_home(tmp_path, "settings-pin-guard.py", "repo-hook.py")
        repo = {"hooks": {"SessionStart": [_group('python3 "$HOME/.claude/hooks/repo-hook.py"')]}}
        glob = {"hooks": {"SessionStart": [_group('python3 "$HOME/.claude/hooks/settings-pin-guard.py"')]}}
        merged = sync.sync_settings(repo, glob, home=home)
        cmds = _commands(merged, "SessionStart")
        assert 'python3 "$HOME/.claude/hooks/repo-hook.py"' in cmds
        assert 'python3 "$HOME/.claude/hooks/settings-pin-guard.py"' in cmds

    def test_global_only_event_is_preserved(self, tmp_path: Path) -> None:
        home = _make_home(tmp_path, "settings-pin-guard.py")
        repo = {"hooks": {"SessionStart": []}}
        glob = {"hooks": {"ConfigChange": [_group('python3 "$HOME/.claude/hooks/settings-pin-guard.py"')]}}
        merged = sync.sync_settings(repo, glob, home=home)
        assert _commands(merged, "ConfigChange") == ['python3 "$HOME/.claude/hooks/settings-pin-guard.py"']

    def test_phantom_hook_missing_script_is_removed(self, tmp_path: Path) -> None:
        home = _make_home(tmp_path)  # no scripts on disk
        repo = {"hooks": {}}
        glob = {"hooks": {"SessionStart": [_group('python3 "$HOME/.claude/hooks/deleted-on-branch.py"')]}}
        merged = sync.sync_settings(repo, glob, home=home)
        assert _commands(merged, "SessionStart") == []

    def test_tilde_path_resolves_against_home(self, tmp_path: Path) -> None:
        home = _make_home(tmp_path, "guard.py")
        repo = {"hooks": {}}
        glob = {"hooks": {"SessionStart": [_group("python3 ~/.claude/hooks/guard.py")]}}
        merged = sync.sync_settings(repo, glob, home=home)
        assert _commands(merged, "SessionStart") == ["python3 ~/.claude/hooks/guard.py"]

    def test_command_without_path_token_is_preserved(self, tmp_path: Path) -> None:
        home = _make_home(tmp_path)
        repo = {"hooks": {}}
        glob = {"hooks": {"Stop": [_group("echo done")]}}
        merged = sync.sync_settings(repo, glob, home=home)
        assert _commands(merged, "Stop") == ["echo done"]

    def test_command_with_one_missing_of_two_paths_is_removed(self, tmp_path: Path) -> None:
        home = _make_home(tmp_path, "a.py")
        repo = {"hooks": {}}
        glob = {"hooks": {"PreToolUse": [_group('python3 "$HOME/.claude/hooks/a.py" "$HOME/.claude/hooks/b.py"')]}}
        merged = sync.sync_settings(repo, glob, home=home)
        assert _commands(merged, "PreToolUse") == []


class TestRepoAuthority:
    def test_repo_hook_not_duplicated_when_in_both(self, tmp_path: Path) -> None:
        home = _make_home(tmp_path, "shared.py")
        cmd = 'python3 "$HOME/.claude/hooks/shared.py"'
        repo = {"hooks": {"SessionStart": [_group(cmd)]}}
        glob = {"hooks": {"SessionStart": [_group(cmd)]}}
        merged = sync.sync_settings(repo, glob, home=home)
        assert _commands(merged, "SessionStart") == [cmd]

    def test_same_command_on_different_event_is_kept_per_event(self, tmp_path: Path) -> None:
        # record-waste on PostToolUseFailure (global) must survive even though the
        # repo registers the same script on another event.
        home = _make_home(tmp_path, "record-waste.py")
        cmd = 'python3 "$HOME/.claude/hooks/record-waste.py"'
        repo = {"hooks": {"PostToolUse": [_group(cmd)]}}
        glob = {"hooks": {"PostToolUseFailure": [_group(cmd)]}}
        merged = sync.sync_settings(repo, glob, home=home)
        assert _commands(merged, "PostToolUseFailure") == [cmd]

    def test_matcher_metadata_of_preserved_group_survives(self, tmp_path: Path) -> None:
        home = _make_home(tmp_path, "guard.py")
        repo = {"hooks": {}}
        glob = {
            "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [_hook('python3 "$HOME/.claude/hooks/guard.py"')]}]}
        }
        merged = sync.sync_settings(repo, glob, home=home)
        assert merged["hooks"]["PreToolUse"][0]["matcher"] == "Bash"


class TestExistingBehaviour:
    def test_non_hook_global_keys_preserved(self, tmp_path: Path) -> None:
        home = _make_home(tmp_path)
        repo = {"hooks": {}}
        glob = {"model": "opus", "hooks": {}}
        merged = sync.sync_settings(repo, glob, home=home)
        assert merged["model"] == "opus"

    def test_attribution_defaults_to_empty(self, tmp_path: Path) -> None:
        home = _make_home(tmp_path)
        merged = sync.sync_settings({}, {}, home=home)
        assert merged["attribution"] == {"commit": "", "pr": ""}

    def test_repo_attribution_wins(self, tmp_path: Path) -> None:
        home = _make_home(tmp_path)
        merged = sync.sync_settings({"attribution": {"commit": "x", "pr": "y"}}, {}, home=home)
        assert merged["attribution"] == {"commit": "x", "pr": "y"}

    def test_two_arg_call_still_works(self) -> None:
        # Callers (and the memory verification recipe) use the two-arg form.
        merged = sync.sync_settings({"hooks": {}}, {"hooks": {}})
        assert "hooks" in merged
