# Disabled hooks

Hooks here are **not registered** in `settings.json` and are intentionally kept out of the live event flow. Archived 2026-06-13 during the toolkit gold-standard audit — all were neutered stubs whose function is now handled elsewhere.

| Hook                                      | Why archived                                                                      |
| ----------------------------------------- | --------------------------------------------------------------------------------- |
| `adr-context-injector.py`                 | Stub — emits empty output; ADR context now handled by `/do` flow.                 |
| `anti-rationalization-injector.py`        | Stub — superseded by `/do` Phase 3 ENHANCE.                                       |
| `capability-catalog-injector.py`          | Stub — routing now lives in `do/SKILL.md` tables.                                 |
| `creation-request-enforcer-userprompt.py` | Stub — superseded by registered `creation-protocol-enforcer.py` + `/do` CLASSIFY. |
| `skill-evaluator.py`                      | Stub — skill routing handled by `do/SKILL.md` + agent descriptions.               |
| `userprompt-datetime-inject.py`           | Stub — superseded by Claude Code native `currentDate` injection.                  |

To re-enable: move the hook back up to `hooks/` and add its registration block to `settings.json`. Verify it fails open (`finally: sys.exit(0)`) before wiring.
