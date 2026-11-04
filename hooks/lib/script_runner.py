"""Run a hook script in-process exactly as runpy.run_path does, minus the recompile.

The dispatchers run every guard via runpy.run_path, which compiles the guard's
source from scratch on every call; run_path never reads or writes __pycache__.
With 7+ guards per tool call that was ~17-25ms of pure compile per hook process.

SourceFileLoader.get_code() returns the same code object but goes through the
normal bytecode cache, so after the first run each guard loads as a .pyc. The
code then executes through runpy's own _run_module_code with the arguments
run_path passes for a plain file, so the guard sees the same globals, the same
temporary __main__ module, and the same argv[0] as before.

If that private runpy helper ever disappears, fall back to run_path unchanged.
"""

import runpy
from importlib.machinery import SourceFileLoader


def run_script(path: str) -> None:
    """Execute the script at `path` as __main__. Exceptions from the script propagate."""
    run_module_code = getattr(runpy, "_run_module_code", None)
    if run_module_code is None:
        runpy.run_path(path, run_name="__main__")
        return
    code = SourceFileLoader("__main__", path).get_code("__main__")
    run_module_code(code, None, "__main__", pkg_name="", script_name=path)
