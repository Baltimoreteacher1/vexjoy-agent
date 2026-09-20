---
name: neft-context-engine
description: Use for any non-trivial implementation, refactor, bug fix, cleanup, repo audit, feature build, or multi-file coding task. Applies a context-efficient inspect-plan-build-verify workflow without bloating CLAUDE.md.
---

# Neft Context Engine

Use this workflow for non-trivial coding work.

## 1. Route
Classify the task:
- bug fix
- feature build
- refactor
- cleanup
- audit
- deployment/config
- documentation
- artifact generation

## 2. Inspect narrowly
Use only the context needed:
- git status
- repo tree summary
- package scripts
- relevant source files
- relevant tests
- recent diffs

Avoid generated output, dependencies, build folders, huge logs, lockfiles, and unrelated docs unless required.

## 3. Plan
Before edits, determine:
- files likely to change
- intended implementation path
- verification command
- risk level

For simple tasks, keep this internal and proceed.

## 4. Implement
Make minimal, high-confidence changes.
Preserve existing behavior and style unless the task requires changing them.
Prefer stable scaffolds, validation, clear error handling, modular helpers, and readable code.

## 5. Verify and repair
Run targeted verification.
If it fails, repair and rerun.
Escalate to broader checks only when needed.

## 6. Final response
Return:
- What changed
- Verification run
- Remaining risks or next step
