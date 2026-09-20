# Agents

Live agent roster for `~/.claude`. This file describes what is actually on disk here — it is
not the upstream toolkit catalog. Curated 2026-09-10 against the work this machine actually
does; the previous off-stack set is archived under `~/.claude/backups/agents-archived-2026-09-10/`
(restore = `mv` back).

`agents/INDEX.json` is generated from the frontmatter of these files:

```sh
uv run --with pyyaml python ~/.claude/scripts/generate-agent-index.py
```

## Domain

| Agent                           | Purpose                                                                                                           |
| ------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `classroom-curriculum-engineer` | `neft-classroom-html-activities` and its worktrees: lessons, variants, generators, validate gates, content safety |
| `cloudflare-workers-engineer`   | Workers/Pages, bindings, D1/KV/R2, Durable Objects, wrangler, deploy guardrails                                   |
| `apps-script-engineer`          | Google Apps Script and Workspace automation: Slides, Sheets, Docs, Forms, Drive, Gmail                            |
| `typescript-frontend-engineer`  | Frontend TypeScript architecture: components, state, build/bundler configuration                                  |
| `typescript-debugging-engineer` | TypeScript debugging: race conditions, async bugs, type and runtime errors                                        |
| `python-general-engineer`       | Python development, debugging, and review (3.12+)                                                                 |
| `database-engineer`             | Schema design, SQL, migrations, indexing, query performance (D1/SQLite, Postgres)                                 |
| `ui-design-engineer`            | UI/UX: design systems, responsive layout, accessibility, motion                                                   |

## Quality and platform

| Agent                         | Purpose                                                                     |
| ----------------------------- | --------------------------------------------------------------------------- |
| `testing-automation-engineer` | node test runner, Vitest, Playwright E2E, coverage, CI wiring               |
| `hook-development-engineer`   | Claude Code Python hooks and the learning database                          |
| `toolkit-governance-engineer` | Toolkit upkeep: skill/agent files, routing tables, ADRs, index regeneration |

## Reviewers

Umbrella reviewers that load reference files on demand rather than one agent per lens.

| Agent             | Purpose                                                                                                     |
| ----------------- | ----------------------------------------------------------------------------------------------------------- |
| `reviewer-code`   | Code quality: conventions, naming, dead code, performance, types, tests, comments, config safety            |
| `reviewer-system` | System level: security, concurrency, error handling, observability, API contracts, migrations, dependencies |

## Lesson pipeline (PPTX → notebook)

| Agent       | Purpose                                                                                               |
| ----------- | ----------------------------------------------------------------------------------------------------- |
| `extractor` | Produce `SCENARIO_EXTRACT` JSON from a source PPTX; halts on low confidence or missing verbatim stems |
| `generator` | Generate PptxGenJS notebook slides from a confirmed extract; runs pre-generation checks P1–P9         |
| `qa-gate`   | Gate checks on generated notebooks, lesson plans, and games; blocks delivery on 2+ critical FAILs     |

## Notes

- The three built-ins (`general-purpose`, `Explore`, `fork`) cover everything not listed here and
  carry the bulk of real delegation traffic. Do not add an agent unless it encodes knowledge those
  three lack.
- `hooks/sync-to-user-claude.py` in `~/claude-code-toolkit` is additive: starting a session inside
  that repo copies its agent files back into this directory. The repo still carries the unpruned
  upstream set, so archived agents can reappear there. Re-run the archive step if they do.
