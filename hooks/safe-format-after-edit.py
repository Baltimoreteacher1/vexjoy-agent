#!/usr/bin/env python3
import json, os, pathlib, subprocess, sys

sys.path.insert(0, str(pathlib.Path(__file__).parent / "lib"))
from stdin_timeout import read_stdin

try:
    data = json.loads(read_stdin(timeout=2))
except Exception:
    sys.exit(0)

tool_input = data.get("tool_input", {}) or {}
file_path = tool_input.get("file_path") or tool_input.get("path")
if not file_path:
    sys.exit(0)

p = pathlib.Path(file_path).expanduser().resolve()
if not p.exists() or not p.is_file():
    sys.exit(0)

blocked_parts = {"node_modules", "dist", "build", ".git", ".next", ".venv", "venv"}
if any(part in blocked_parts for part in p.parts):
    sys.exit(0)

suffix = p.suffix.lower()


def run(cmd):
    try:
        subprocess.run(
            cmd,
            cwd=str(p.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
        )
    except Exception:
        pass


if suffix in {
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".json",
    ".css",
    ".scss",
    ".html",
    ".md",
    ".mdx",
    ".yaml",
    ".yml",
}:
    run(["prettier", "--write", str(p)])
elif suffix == ".py":
    run(["ruff", "format", str(p)])
elif suffix in {".sh", ".bash", ".zsh"}:
    run(["shfmt", "-w", str(p)])

sys.exit(0)
