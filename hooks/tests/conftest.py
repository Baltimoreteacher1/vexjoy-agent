"""Skip test modules whose hook is not installed in ~/.claude/hooks/.

Several test files here are synced from claude-code-toolkit but test hooks that
this machine deliberately does not run (archived, disabled, or never installed).
Those modules load their hook at import time via ``spec.loader.exec_module``, so
a missing hook raises FileNotFoundError during *collection* and aborts the whole
suite -- 593 passing tests become unrunnable because of one absent file.

Rather than hardcode a list that rots, read each test module's ``HOOK_PATH``
declaration and ignore the module only when that exact file is absent. A renamed
hook (test_ref_delete_guard.py -> pretool-ref-delete-guard.py) is therefore still
collected, because it names its real hook and that hook exists.
"""

import re
from pathlib import Path

_TESTS_DIR = Path(__file__).parent
_HOOKS_DIR = _TESTS_DIR.parent

# Matches: HOOK_PATH = Path(__file__).parent.parent / "some-hook.py"
_HOOK_PATH_RE = re.compile(r'HOOK_PATH\s*=.*?/\s*"([^"]+\.py)"')

collect_ignore = []

for test_file in sorted(_TESTS_DIR.glob("test_*.py")):
    match = _HOOK_PATH_RE.search(
        test_file.read_text(encoding="utf-8", errors="replace")
    )
    if match and not (_HOOKS_DIR / match.group(1)).exists():
        collect_ignore.append(test_file.name)
