#!/usr/bin/env python3
# hook-version: 1.0.0
"""
Stop Hook: Propose graduation of high-confidence learnings into agent/skill files.

Runs at session end to identify learning DB entries that have proven
reliable enough (high confidence, multiple observations) to be permanently
codified into the relevant agent or skill markdown files.

Writes proposal files to ~/.claude/graduation-proposals/ for human review.
Each proposal includes the learning text, target file, suggested section,
and rationale (confidence score + observation count).

Design Principles:
- Non-blocking (always exits 0)
- Silent when no candidates exist
- Idempotent migration (safe to re-run)
- Only stdlib dependencies
"""

import json
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# Graduation thresholds
MIN_CONFIDENCE = 0.85
# Evidence = how many times the entry has actually been seen or reconfirmed.
# Two writers feed this: record_learning() bumps observation_count, while
# boost_confidence() (the reinforcement path that is the ONLY way an entry
# reaches MIN_CONFIDENCE) bumps success_count. Gating on observation_count
# alone made graduation unreachable by construction. Take whichever is higher.
MIN_EVIDENCE = 3

# Counter rows written by task-completion instrumentation: key is a bare integer
# and the row carries no success signal. High observation_count, zero knowledge.
NOISE_TOPICS = {"task-completion"}

# Rows written by the hook test suite against the real DB. They are the only
# entries in the database that reach MIN_CONFIDENCE, so without this filter the
# first thing graduation would ever promote is "Test error ... -> Test solution".
# (The 42 historical rows were purged 2026-09-10 and the suite now isolates via
# CLAUDE_LEARNING_DIR; the filter stays as a backstop.)
NOISE_SOURCES = {"test"}

# An error that was recorded but never successfully fixed. error-learner.py
# stamps this instead of fabricating a solution. Recurrence is not knowledge —
# promoting "this keeps failing and we never found out why" into the always-
# loaded rules file would be worse than promoting nothing.
NO_SOLUTION_MARKER = "(no confirmed fix yet)"

# Repo root for resolving agent/skill file paths
REPO_ROOT = Path(__file__).resolve().parent.parent

# Where to write proposals
PROPOSALS_DIR = Path.home() / ".claude" / "graduation-proposals"


def _resolve_target_file(topic: str) -> str | None:
    """Map a learning topic to its agent or skill file path."""
    # Check if topic matches an agent file
    agent_file = REPO_ROOT / "agents" / f"{topic}.md"
    if agent_file.exists():
        return str(agent_file)

    # Check if topic matches a skill directory
    skill_file = REPO_ROOT / "skills" / topic / "SKILL.md"
    if skill_file.exists():
        return str(skill_file)

    # Check if topic matches a pipeline directory
    pipeline_file = REPO_ROOT / "pipelines" / topic / "SKILL.md"
    if pipeline_file.exists():
        return str(pipeline_file)

    # Fallback destination. Error learnings are keyed by signature hash and carry
    # topic='unknown', so they matched nothing above and every proposal was
    # stamped "Target file: UNKNOWN" — a proposal with nowhere to go. Files in
    # ~/.claude/rules/ are loaded into every session, so that is a destination
    # where a graduated learning actually takes effect.
    return str(Path.home() / ".claude" / "rules" / "learned-errors.md")


def _format_proposal(topic: str, entries: list[dict], target_file: str | None) -> str:
    """Format a graduation proposal as markdown."""
    lines = [
        f"# Graduation Proposal: {topic}",
        "",
        f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Target file**: {target_file or 'UNKNOWN — no matching agent/skill found'}",
        f"**Entries**: {len(entries)}",
        "",
        "---",
        "",
    ]

    for entry in entries:
        lines.extend(
            [
                f"## {entry['category']}: {entry['key']}",
                "",
                f"**Confidence**: {entry['confidence']:.2f}  ",
                f"**Observations**: {entry['observation_count']}  ",
                f"**Source**: {entry['source']}  ",
                f"**First seen**: {entry['first_seen']}  ",
                f"**Last seen**: {entry['last_seen']}",
                "",
                "### Learning",
                "",
                entry["value"],
                "",
                "### Suggested Addition",
                "",
                "Add to the **Known Issues** or **Anti-Patterns** section:",
                "",
                "```markdown",
                f"- **{entry['key']}**: {entry['value'].split(chr(10))[0]}",
                "```",
                "",
                "### Rationale",
                "",
                f"This learning has been observed {entry['observation_count']} times "
                f"with {entry['confidence']:.0%} confidence. "
                f"It qualifies for permanent inclusion in the target file.",
                "",
                "---",
                "",
            ]
        )

    lines.extend(
        [
            "## How to Graduate",
            "",
            "1. Review each entry above",
            "2. Edit the target file to include the knowledge",
            "3. Run: `python3 scripts/learning-db.py graduate TOPIC KEY TARGET`",
            "   to mark the entry as graduated in the DB",
            "",
        ]
    )

    return "\n".join(lines)


def main():
    debug = os.environ.get("CLAUDE_HOOKS_DEBUG")

    try:
        # Determine DB path (same logic as learning_db_v2.py)
        db_dir = os.environ.get("CLAUDE_LEARNING_DIR")
        if db_dir:
            db_path = Path(db_dir) / "learning.db"
        else:
            db_path = Path.home() / ".claude" / "learning" / "learning.db"

        # Silent exit if DB doesn't exist
        if not db_path.exists():
            if debug:
                print("[graduation] No learning.db found, skipping", file=sys.stderr)
            return

        conn = sqlite3.connect(str(db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row

        try:
            # Query graduation candidates
            rows = conn.execute(
                """
                SELECT topic, key, value, category, confidence,
                       observation_count, source, first_seen, last_seen
                FROM learnings
                WHERE confidence >= ?
                  AND MAX(observation_count, success_count + 1) >= ?
                  AND topic NOT IN (SELECT value FROM json_each(?))
                  AND source NOT IN (SELECT value FROM json_each(?))
                  AND value NOT LIKE ?
                  AND (graduated_to IS NULL OR graduated_to = '')
                  AND graduation_proposed_at IS NULL
                """,
                (
                    MIN_CONFIDENCE,
                    MIN_EVIDENCE,
                    json.dumps(sorted(NOISE_TOPICS)),
                    json.dumps(sorted(NOISE_SOURCES)),
                    f"%{NO_SOLUTION_MARKER}%",
                ),
            ).fetchall()

            if not rows:
                if debug:
                    print("[graduation] No candidates found", file=sys.stderr)
                return

            # Group by topic
            groups: dict[str, list[dict]] = defaultdict(list)
            for row in rows:
                entry = dict(row)
                groups[entry["topic"]].append(entry)

            # Create proposals directory
            PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)

            date_prefix = datetime.now().strftime("%Y-%m-%d")
            proposal_count = 0

            for topic, entries in groups.items():
                target_file = _resolve_target_file(topic)
                content = _format_proposal(topic, entries, target_file)

                # Sanitize topic for filename
                safe_topic = topic.replace("/", "-").replace(" ", "-")
                filename = f"{date_prefix}-{safe_topic}.md"
                proposal_path = PROPOSALS_DIR / filename

                proposal_path.write_text(content, encoding="utf-8")
                proposal_count += 1

            # Mark all proposed entries
            topics_keys = [(row["topic"], row["key"]) for row in rows]
            for topic, key in topics_keys:
                conn.execute(
                    """
                    UPDATE learnings
                    SET graduation_proposed_at = datetime('now')
                    WHERE topic = ? AND key = ?
                    """,
                    (topic, key),
                )
            conn.commit()

            print(f"[graduation] {proposal_count} proposal(s) written to {PROPOSALS_DIR}/ ({len(rows)} entries total)")

        finally:
            conn.close()

    except Exception as exc:
        # Stop hooks must NEVER fail the session
        if os.environ.get("CLAUDE_HOOKS_DEBUG"):
            print(f"[graduation] Error: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
