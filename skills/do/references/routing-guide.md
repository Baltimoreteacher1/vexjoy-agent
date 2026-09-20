# Routing System

The `/do` command routes requests to appropriate agents and skills.

## How Routing Works

1. **Classify** - Determine request complexity (Trivial, Simple, Medium, Complex)
2. **Route** - Run `scripts/index-router.py` for trigger matching, apply force-routes or select from scored candidates, override skill based on task verb
3. **Enhance** - Stack additional skills based on request signals (e.g., "with tests" adds test-driven-development)
4. **Execute** - Create plan (Simple+), invoke agent with skill methodology
5. **Learn** - Record routing outcome and session insights to `learning.db`

## Agent Selection Triggers

| Triggers | Agent |
|----------|-------|
| python, .py, pip, pytest | `general-purpose` |
| react, next.js | `general-purpose` |

## Force-Routed Skills

These skills **MUST** be invoked when their triggers appear:

| Triggers | Skill |
|----------|-------|
| Typo, one-line fix, trivial mechanical change | `fast` |
| Small self-contained change, add CLI flag, extract helper | `quick` |
| Push branch, create PR, open PR, PR status, fix PR comments, CI passed, GitHub Actions status, build results, name branch, generate branch name, stage files, commit, save work, checkpoint, codex review, second opinion | `pr-workflow` |
| New feature design, plan, implement, validate, release | `feature-lifecycle` |
| Scan and fix AI patterns across docs/content | `de-ai-pipeline` |
| Improve toolkit, evaluate repo, audit system, self-improvement | `toolkit-improvement` |

> For full routing tables with all agents and skills, see `skills/do/references/routing-tables.md`.
