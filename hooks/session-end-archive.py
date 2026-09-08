#!/usr/bin/env python3
"""SessionEnd hook — archive the transcript and index the session.

Why: Stop / StopFailure / PostCompact fire mid-session and can be missed on `/clear`
or a hard exit. SessionEnd is the only event guaranteed to fire when a session is
actually over, so it is the correct place for durable archival. Complements
precompact-archive.py (which only covers the compaction path).

Writes:
  ~/.claude/transcripts/<YYYY-MM-DD>/<session_id>.jsonl   (copy of the transcript)
  ~/.claude/transcripts/index.jsonl                       (one line per session)

Retention: prunes archived transcripts older than $CLAUDE_TRANSCRIPT_RETENTION_DAYS
(default 60) so this never grows unbounded.

Fail-open: never blocks. Any error exits 0 silently.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path.home() / ".claude" / "transcripts"
INDEX = ROOT / "index.jsonl"
DEFAULT_RETENTION_DAYS = 60


def _retention_days() -> int:
    try:
        return max(1, int(os.environ.get("CLAUDE_TRANSCRIPT_RETENTION_DAYS", "")))
    except (TypeError, ValueError):
        return DEFAULT_RETENTION_DAYS


def _prune(cutoff: float) -> None:
    if not ROOT.exists():
        return
    for day_dir in ROOT.iterdir():
        if not day_dir.is_dir():
            continue
        for f in day_dir.glob("*.jsonl"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
            except OSError:
                pass
        try:
            next(day_dir.iterdir())
        except StopIteration:
            day_dir.rmdir()
        except OSError:
            pass


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    session_id = str(payload.get("session_id") or "unknown")
    transcript = payload.get("transcript_path") or ""
    reason = payload.get("reason") or "unknown"
    cwd = payload.get("cwd") or ""

    day = time.strftime("%Y-%m-%d")
    dest_dir = ROOT / day
    archived = None

    try:
        src = Path(transcript)
        if transcript and src.is_file():
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / f"{session_id}.jsonl"
            shutil.copy2(src, dest)
            archived = str(dest)
    except Exception:
        pass

    try:
        ROOT.mkdir(parents=True, exist_ok=True)
        with INDEX.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                        "session_id": session_id,
                        "reason": reason,
                        "cwd": cwd,
                        "project": Path(cwd).name if cwd else None,
                        "archived": archived,
                    }
                )
                + "\n"
            )
    except Exception:
        pass

    try:
        _prune(time.time() - _retention_days() * 86400)
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
