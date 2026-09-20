---
name: neft-verification-pass
description: Use when finishing code changes, reviewing a diff, preparing a PR, auditing a repo, or checking whether work is safe to ship. Focuses on verification, risk, tests, and final QA.
---

# Neft Verification Pass

Run this before declaring work complete.

## Inspect
Check:
- git status
- git diff
- changed files
- package/test scripts
- config changes
- generated files
- secrets/local paths
- dependency changes
- permissions/deploy changes

## Verify
Run the smallest reliable set:
- targeted tests first
- lint/typecheck when relevant
- build when relevant
- smoke check when relevant

## Repair
If verification fails:
1. find root cause
2. make smallest safe fix
3. rerun check

## Final report
Include:
- changed files
- verification commands/results
- anything not verified
- real risks only
