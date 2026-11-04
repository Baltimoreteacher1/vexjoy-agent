#!/usr/bin/env python3
"""Tests the sync hook's local opt-out list (~/.claude/sync-exclude.txt).

The sync is additive, so deleting curated content from ~/.claude does not stick:
the next session started inside this repo copies it back. `sync-exclude.txt` is
how a removal is made durable without deleting anything from the repo.

Run with: python3 -m pytest hooks/tests/test_sync_exclude.py -v
"""

import importlib.util
from pathlib import Path
from typing import ClassVar

import pytest

HOOK_PATH = Path(__file__).resolve().parents[1] / "sync-to-user-claude.py"

spec = importlib.util.spec_from_file_location("sync_to_user_claude", HOOK_PATH)
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


class TestLoadSyncExcludes:
    """Parsing ~/.claude/sync-exclude.txt."""

    def test_missing_file_yields_no_excludes(self, tmp_path: Path) -> None:
        assert sync.load_sync_excludes(tmp_path) == []

    def test_comments_and_blank_lines_are_ignored(self, tmp_path: Path) -> None:
        (tmp_path / "sync-exclude.txt").write_text(
            "# header comment\n\nagents/nodejs-api-engineer\n   \nagents/reviewer-domain   # trailing comment\n"
        )
        assert sync.load_sync_excludes(tmp_path) == [
            "agents/nodejs-api-engineer",
            "agents/reviewer-domain",
        ]

    def test_leading_and_trailing_slashes_are_stripped(self, tmp_path: Path) -> None:
        (tmp_path / "sync-exclude.txt").write_text("/agents/data-engineer/\n")
        assert sync.load_sync_excludes(tmp_path) == ["agents/data-engineer"]


class TestIsExcluded:
    """Prefix matching against a destination-relative path."""

    EXCLUDES: ClassVar[list[str]] = ["agents/nodejs-api-engineer", "skills/go-patterns"]

    @pytest.mark.parametrize(
        "dst_rel",
        [
            "agents/nodejs-api-engineer.md",
            "agents/nodejs-api-engineer/references/auth-patterns.md",
            "skills/go-patterns/SKILL.md",
        ],
    )
    def test_matches_agent_file_and_its_reference_directory(self, dst_rel: str) -> None:
        assert sync.is_excluded(dst_rel, self.EXCLUDES)

    @pytest.mark.parametrize(
        "dst_rel",
        [
            "agents/python-general-engineer.md",
            "agents/nodejs-api-engineer-compact.md",
            "skills/go-patterns-extra/SKILL.md",
            "hooks/sync-to-user-claude.py",
        ],
    )
    def test_does_not_match_unrelated_or_prefix_lookalike_paths(self, dst_rel: str) -> None:
        assert not sync.is_excluded(dst_rel, self.EXCLUDES)

    def test_empty_exclude_list_matches_nothing(self) -> None:
        assert not sync.is_excluded("agents/nodejs-api-engineer.md", [])


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
