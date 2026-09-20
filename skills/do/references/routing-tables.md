# Complete Routing Tables

Extended routing tables for the `/do` router. The main SKILL.md contains routing instructions. This file contains the full category-specific skill routing and the domain agent table.

**How to read these tables**: Each entry describes what the agent/skill IS FOR and, where false positives have occurred historically, what it is NOT for. The LLM reads these descriptions and judges intent — it does not match keywords.

---

## Domain Agents

The 11 domain-specialist engineer agents were archived 2026-09-12 (usage evidence:
5 lifetime invocations vs 1,240 for general-purpose; copies in
`~/.claude/backups/agents-archived-2026-09-12/`). Domain work — Python, TypeScript,
Cloudflare Workers, databases, Apps Script, classroom curriculum, hooks, UI, testing,
toolkit governance — routes to **general-purpose**, paired with the matching skill
from the tables below (e.g. `python-quality-gate`, `typescript-check`, `wrangler`,
`e2e-testing`). The agents that remain are the pipeline and review specialists:

| Agent               | When to Route Here                                                                                     |
| ------------------- | ------------------------------------------------------------------------------------------------------ |
| **extractor**       | A PPTX file is present and the trigger is `Pipeline:` or `NB:` — produces SCENARIO_EXTRACT JSON.        |
| **generator**       | After the user confirms SCENARIO_EXTRACT — generates PptxGenJS notebook slides per the generator spec.  |
| **qa-gate**         | After any notebook, lesson plan, or game generation — runs gate checks and blocks delivery on failures. |
| **reviewer-code**   | Code-quality review: conventions, naming, dead code, performance, test coverage.                        |
| **reviewer-system** | System-level review: security, concurrency, error handling, observability, API contracts.               |

---

## Process & Execution Skills

| Skill                              | When to Route Here                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| ---------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **read-only-ops**                  | User explicitly wants read-only operations: browsing, exploring, or examining without any modifications.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| **distinctive-frontend-design**    | User wants context-driven aesthetic exploration for a frontend project with anti-cliche validation: typography exploration, visual identity, design language.                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| **do**                             | Primary entry point for all delegated work: classifies user requests and routes to the correct agent + skill combination.                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| **install**                        | User wants to verify Claude Code Toolkit installation, diagnose setup issues, or check if the toolkit is correctly configured.                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| **threejs-builder**                | User wants to build a Three.js 3D web application: scenes, WebGL, 3D animation, or 3D graphics in the browser. 4-phase workflow: Design, Build, Animate, Polish.                                                                                                                                                                                                                                                                                                                                                                                                                              |
| **worktree-agent**                 | Mandatory rules for agents operating in git worktree isolation: verify working directory, create feature branches, use absolute paths. Not user-invoked directly.                                                                                                                                                                                                                                                                                                                                                                                                                             |

---

## Analysis & Discovery Skills

| Skill                             | When to Route Here                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| --------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **pr-workflow** (miner mode)      | User wants to extract review comments or learnings from past GitHub PRs, or coordinate batch mining.                                                                                                                                                                                                                                                                                                                                                                        |
| **routing-table-updater**         | User wants to update routing tables after adding or changing agents/skills.                                                                                                                                                                                                                                                                                                                                                                                                 |
| **retro**                         | User wants to interact with the learning system: view stats, list accumulated knowledge, search learnings, or graduate mature entries into agents/skills.                                                                                                                                                                                                                                                                                                                   |
| **generate-claudemd**             | User wants to generate a project-specific CLAUDE.md by analyzing the current repository's structure and conventions.                                                                                                                                                                                                                                                                                                                                                        |

---

## PR & Git Skills

| Skill                   | When to Route Here                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **pr-workflow (FORCE)** | User wants to get local code changes onto GitHub — pushing a branch, creating a PR, syncing local commits to the remote, or creating a git commit from local changes (commit intent). Also handles: PR status checks, fixing review comments, cleaning up branches after merge, addressing PR feedback, mining tribal knowledge from PRs, generating/validating Git branch names (branch-name intent), checking GitHub Actions CI status after a push (ci-check intent), getting a second-opinion code review from OpenAI Codex CLI (codex-review intent). Common phrasings: "open a pull request", "create a PR", "make a PR", "submit PR", "push and PR", "pr status", "fix PR comments", "clean up branches", "mine PRs", "generate branch name", "check CI", "did CI pass", "commit this", "save my work", "checkpoint", "codex review", "second opinion". NOT: "push back" (disagree with a decision), "push the boundaries" (explore limits), "check this code" (review), "check my logic" (analysis), "commit to this approach" (deciding), "commit to the team" (dedication). The intent must be about git/GitHub operations. |
| **/pr-review command**  | User wants a comprehensive code review of a PR with retro learning applied. This is a command, not a skill — invoke it directly. |

### PR Workflow Policies

| Repo Type                                    | Detection                                | Commit/Push/PR                               | Review Gate                                | Merge                         |
| -------------------------------------------- | ---------------------------------------- | -------------------------------------------- | ------------------------------------------ | ----------------------------- |
| **protected-org** (configured organizations) | `scripts/classify-repo.py` pattern match | **Human-gated**: confirm each step with user | Their reviewers handle review              | **NEVER auto-merge**          |
| **personal** (all other repos)               | Default                                  | Auto-execute                                 | `/pr-review` → fix loop (max 3 iterations) | Create PR after review passes |

---

## Content Creation Skills

| Skill                      | When to Route Here                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| -------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **gemini-image-generator** | User wants to generate images from text prompts via Google Gemini: sprites, character art, or AI-generated visuals.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |

---

## Voice Skills

## Pipeline Skills

All workflow pipelines live in `skills/workflow/references/` and are accessed via the workflow umbrella skill.

| Pipeline                                              | When to Route Here                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | Phases                                                                                                 |
| ----------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| **workflow** (umbrella)                               | All structured multi-phase workflows. Routes to the correct workflow based on intent. Includes: toolkit-improvement, system-upgrade, research-to-article, explore, doc-generation, comprehensive-review, article-evaluation, voice-calibrator, de-ai, auto-pipeline, and more. Each workflow lives in `skills/workflow/references/`.                                                                                                                                                                                  |
| **system-upgrade** (general-purpose)          | User wants to upgrade the Claude Code toolkit after a model update, apply system-wide changes, or roll out agent improvements. NOT: upgrading a specific library dependency in user code.                                                                                                                                                                                                                                                                                                                             | CHANGELOG → AUDIT → PLAN → IMPLEMENT → VALIDATE → DEPLOY                                               |
| **workflow** (skill-creation, skill-creator)          | User wants to create a new skill with formal quality gates, phase structure, and integration.                                                                                                                                                                                                                                                                                                                                                                                                                         | DISCOVER → DESIGN → SCAFFOLD → VALIDATE → INTEGRATE                                                    |
| **pr-workflow** (pipeline mode)                       | User wants the full structured PR workflow with review gates.                                                                                                                                                                                                                                                                                                                                                                                                                                                         | CLASSIFY → STAGE → REVIEW → COMMIT → PUSH → CREATE → VERIFY → CLEANUP                                  |

### Workflow Companion Map

Workflows that work together in common sequences:

| Workflow                | Sequence                                                        | When                                             |
| ----------------------- | --------------------------------------------------------------- | ------------------------------------------------ |
| **Feature lifecycle**   | workflow (explore) → workflow-orchestrator → pr-workflow        | Understand → implement → ship                    |
| **Code review**         | workflow (comprehensive-review) → pr-workflow                   | Review then submit                               |
| **Agent improvement**   | agent-upgrade → skill-creator                                   | Audit agent, then scaffold missing skills        |
| **Toolkit improvement** | workflow (toolkit-improvement) → system-upgrade → agent-upgrade | Evaluate → fix → upgrade system → upgrade agents |
| **System upgrade**      | system-upgrade → agent-upgrade                                  | Upgrade system, then individual agents           |
| **Documentation**       | workflow (explore) → workflow (doc-generation)                  | Understand codebase → generate docs              |

---



## Validation Skills

| Skill                    | When to Route Here                                                                        |
| ------------------------ | ----------------------------------------------------------------------------------------- |

---

## Decision Support Skills

Umbrella skill for all C-suite decision support. Detects mode (STRATEGY, TECHNOLOGY, GROWTH, COMPETITIVE, EVALUATION) and loads domain-specific references on demand.

| Skill | When to Route Here |
| ----- | ------------------ |

---


## Reviewer Agents

Consolidated reviewer agents, each covering multiple review perspectives:

| Agent                     | When to Route Here                                                                                                                                                                                                                                                                                    |
| ------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **reviewer-code**         | Code quality review: conventions, naming, dead code, performance, types, tests, comments, config safety. Use for code style, readability, simplification, language idioms, naming consistency, unused code, comment accuracy, hot paths, type design, test coverage, and configuration review.        |
| **reviewer-system**       | System review: security, concurrency, errors, observability, APIs, migrations, dependencies, docs. Use for vulnerability scans, race conditions, goroutine leaks, silent failures, error messages, logging quality, API contracts, migration safety, dependency audits, and documentation validation. |

---

## Quick Routing Examples

| Request                                   | Routes To                                               | Reasoning                                              |
| ----------------------------------------- | ------------------------------------------------------- | ------------------------------------------------------ |
| "add auth to Python API"                  | general-purpose + workflow-orchestrator         | Python domain, multi-step implementation               |
| "roast this design doc"                   | roast (5 personas)                                      | Multi-persona critique                                 |
| "execute plan with subagents"             | subagent-driven-development                             | Explicit subagent execution                            |
| "debug TypeScript race condition"         | general-purpose + systematic-debugging    | TS debugging domain                                    |
| "comprehensive code review"               | parallel-code-review (3 reviewers)                      | Multi-reviewer parallel review                         |
| "review this PR"                          | /pr-review command (retro-enabled)                      | PR review command                                      |
| "submit a PR"                             | pr-workflow (pipeline mode)                             | Full PR workflow with gates                            |
| "push my changes"                         | **pr-workflow (FORCE)**                                 | Intent: get local changes onto GitHub                  |
| "push back on this decision"              | (not a routing target)                                  | Intent: disagree — "push" is not a git push            |
| "commit this"                             | **pr-workflow (FORCE)**                                 | Intent: create a git commit (commit intent)            |
| "commit to this approach"                 | (not a routing target)                                  | Intent: decide — "commit" is not a git commit          |
| "did CI pass?"                            | **pr-workflow (FORCE)**                                 | Intent: check CI status (ci-check intent)              |
| "check my logic here"                     | (domain agent + review)                                 | Intent: review — not CI                                |
| "get a second opinion on this code"       | **pr-workflow (FORCE)**                                 | Cross-model review via Codex CLI (codex-review intent) |
| "codex review this PR"                    | **pr-workflow (FORCE)**                                 | Explicit Codex review request (codex-review intent)    |
| "create a pipeline for X"                 | general-purpose + workflow               | Pipeline creation                                      |
| "improve the toolkit"                     | toolkit-improvement (FORCE)                             | Full 10-phase evaluation + improvement                 |
| "evaluate the repo"                       | toolkit-improvement (FORCE)                             | Full 10-phase evaluation + improvement                 |
| "audit the system"                        | toolkit-improvement (FORCE)                             | Full 10-phase evaluation + improvement                 |
| "find issues"                             | toolkit-improvement (FORCE)                             | Full 10-phase evaluation + improvement                 |
| "what can be better"                      | toolkit-improvement (FORCE)                             | Full 10-phase evaluation + improvement                 |
| "self-improvement"                        | toolkit-improvement (FORCE)                             | Full 10-phase evaluation + improvement                 |
| "upgrade system for new Claude version"   | general-purpose + system-upgrade                | System-wide upgrade                                    |
| "create skill with quality gates"         | skill-creator + workflow (skill-creation)               | Formal skill creation                                  |
| "create hook (formal, with perf test)"    | general-purpose + workflow (hook-development) | Formal hook creation                                   |
| "research with saved artifacts"           | general-purpose + research-pipeline       | Formal research pipeline                               |
| "upgrade this specific agent"             | skill-creator + agent-upgrade                           | Single agent improvement                               |
| "create a 3D scene"                       | general-purpose + threejs-builder          | Frontend domain, 3D task                               |
| "generate image with Python"              | general-purpose + gemini-image-generator        | Python domain, image generation                        |
| "open a pull request"                     | **pr-workflow (FORCE)**                                 | Intent: create a PR on GitHub                          |
| "make a PR"                               | **pr-workflow (FORCE)**                                 | Intent: create a PR on GitHub                          |
| "save my work"                            | **pr-workflow (FORCE)**                                 | Intent: commit current changes (commit intent)         |
| "checkpoint"                              | **pr-workflow (FORCE)**                                 | Intent: save progress as a commit (commit intent)      |
| "I'm stuck"                               | workflow-help                                           | User is lost — guide them                              |
| "where do I start"                        | workflow-help                                           | User needs orientation                                 |
| "why is this broken"                      | systematic-debugging                                    | Diagnosis request — root cause analysis                |
| "figure out why"                          | systematic-debugging                                    | Diagnosis request — root cause analysis                |
| "it's slow"                               | systematic-debugging                                    | Performance issue — diagnosis needed                   |
| "clean this up"                           | systematic-refactoring                                  | Code improvement — refactoring                         |
| "make this better"                        | systematic-refactoring                                  | Code quality improvement                               |
| "review this"                             | comprehensive-review                                    | Multi-wave code review                                 |
| "look at this code"                       | comprehensive-review                                    | Code review request                                    |
