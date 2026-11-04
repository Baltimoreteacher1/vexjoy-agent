#!/usr/bin/env python3
"""Notification hook — surface blocked/idle sessions while Joel is AFK.

Why: night-shift + AFK runs (com.neft.nightshift, afk-mode.py) mean Claude can sit
blocked on a permission prompt or idle for hours with nobody watching. Claude Code
fires `Notification` for exactly those moments; without a hook they are invisible
outside the TUI.

Delivery, best-effort and in order:
  1. macOS Notification Center via osascript (always available on darwin).
  2. ntfy.sh topic, if $NTFY_TOPIC is set (reaches the phone).

Fail-open: never blocks the session. Any error exits 0 silently.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

LOG = Path.home() / ".claude" / "telemetry" / "notifications.jsonl"
TIMEOUT = 5


def _osascript(title: str, message: str) -> None:
    if sys.platform != "darwin":
        return
    osa = shutil.which("osascript")
    if not osa:
        return

    # Quote by escaping backslashes then double quotes, so AppleScript sees literals.
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')

    script = (
        f'display notification "{esc(message[:240])}" '
        f'with title "{esc(title[:80])}" sound name "Submarine"'
    )
    subprocess.run([osa, "-e", script], timeout=TIMEOUT, capture_output=True)


def _ntfy(title: str, message: str) -> None:
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        return
    curl = shutil.which("curl")
    if not curl:
        return
    base = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    subprocess.run(
        [
            curl,
            "-fsS",
            "-m",
            str(TIMEOUT),
            "-H",
            f"Title: {title[:80]}",
            "-H",
            "Priority: default",
            "-H",
            "Tags: robot",
            "-d",
            message[:1000],
            f"{base}/{topic}",
        ],
        timeout=TIMEOUT + 2,
        capture_output=True,
    )


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    message = str(payload.get("message") or "").strip()
    if not message:
        return 0

    cwd = payload.get("cwd") or ""
    project = Path(cwd).name if cwd else "claude"
    title = f"Claude Code — {project}"

    for send in (_osascript, _ntfy):
        try:
            send(title, message)
        except Exception:
            pass

    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "session_id": payload.get("session_id"),
                        "cwd": cwd,
                        "message": message,
                    }
                )
                + "\n"
            )
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
