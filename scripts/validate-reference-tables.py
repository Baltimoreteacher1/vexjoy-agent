#!/usr/bin/env python3
"""Validate reference loading table coverage across agents and skills.

Reports agents and skills that have references/ directories but no
Reference Loading Table in their .md file. Loading tables tell agents
which reference files to load based on task signals.

Usage:
    python3 scripts/validate-reference-tables.py
    python3 scripts/validate-reference-tables.py --min-refs 3  # only report gaps with 3+ refs
"""

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

LOADING_TABLE_PATTERNS = [
    re.compile(r"Reference Loading", re.IGNORECASE),
    re.compile(r"\|\s*Signal\s*\|.*\|\s*Load", re.IGNORECASE),
    re.compile(r"\|\s*Load\s*\|.*\|\s*Signal", re.IGNORECASE),
    re.compile(r"When to load", re.IGNORECASE),
    re.compile(r"\|\s*Trigger\s*\|.*\|\s*File", re.IGNORECASE),
]


def has_loading_table(content: str) -> bool:
    return any(p.search(content) for p in LOADING_TABLE_PATTERNS)


def audit_agents(min_refs: int) -> list[tuple[str, int]]:
    gaps = []
    for refs_dir in sorted(REPO_ROOT.glob("agents/*/references")):
        if not refs_dir.is_dir():
            continue
        name = refs_dir.parent.name
        md = REPO_ROOT / "agents" / f"{name}.md"
        ref_count = len(list(refs_dir.glob("*.md")))
        if ref_count < min_refs:
            continue
        if md.exists() and not has_loading_table(md.read_text()):
            gaps.append((name, ref_count))
    return gaps


def audit_skills(min_refs: int) -> list[tuple[str, int]]:
    gaps = []
    for refs_dir in sorted(REPO_ROOT.glob("skills/*/references")):
        if not refs_dir.is_dir():
            continue
        name = refs_dir.parent.name
        skill_md = REPO_ROOT / "skills" / name / "SKILL.md"
        ref_count = len(list(refs_dir.glob("*.md")))
        if ref_count < min_refs:
            continue
        if skill_md.exists() and not has_loading_table(skill_md.read_text()):
            gaps.append((name, ref_count))
    return gaps


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit reference loading table coverage")
    parser.add_argument("--min-refs", type=int, default=1, help="Only report gaps with N+ reference files")
    args = parser.parse_args()

    agent_gaps = audit_agents(args.min_refs)
    skill_gaps = audit_skills(args.min_refs)

    total_agents = len(list(REPO_ROOT.glob("agents/*/references")))
    total_skills = len(list(REPO_ROOT.glob("skills/*/references")))

    if not agent_gaps and not skill_gaps:
        print(f"PASS: All agents ({total_agents}) and skills ({total_skills}) with references have loading tables")
        return 0

    if agent_gaps:
        print(f"Agents missing loading tables: {len(agent_gaps)}/{total_agents}")
        for name, count in sorted(agent_gaps, key=lambda x: -x[1]):
            print(f"  {name}: {count} refs")

    if skill_gaps:
        print(f"\nSkills missing loading tables: {len(skill_gaps)}/{total_skills}")
        for name, count in sorted(skill_gaps, key=lambda x: -x[1]):
            print(f"  {name}: {count} refs")

    print(f"\nTotal gaps: {len(agent_gaps) + len(skill_gaps)} (use --min-refs to filter)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
