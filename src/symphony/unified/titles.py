"""Session titles from Claude Code transcripts (the name shown on terminal tabs).

Claude Code appends `{"type": "ai-title", "aiTitle": ...}` lines to
`~/.claude/projects/<encoded cwd>/<session id>.jsonl`; the newest one is the
title. Only the tail of the file is read, and results are cached by
(mtime, size) so frequent polling stays cheap. Nothing is written.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

TAIL_BYTES = 256 * 1024
DEFAULT_ROOT = Path.home() / ".claude" / "projects"

_cache: dict[str, tuple[float, int, str | None]] = {}


def transcript_dir_for(cwd: str, root: Path = DEFAULT_ROOT) -> Path:
    """Claude Code names a project's transcript folder after its cwd."""
    return root / re.sub(r"[^A-Za-z0-9]", "-", cwd)


def _last_title(text: str) -> str | None:
    title = None
    for line in text.splitlines():
        if '"ai-title"' not in line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue  # the tail read may start mid-line
        if entry.get("type") == "ai-title" and isinstance(entry.get("aiTitle"), str):
            title = entry["aiTitle"].strip() or title
    return title


def title_from_transcript(path: Path) -> str | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    cached = _cache.get(str(path))
    if cached and cached[0] == stat.st_mtime and cached[1] == stat.st_size:
        return cached[2]
    try:
        with path.open("rb") as fh:
            if stat.st_size > TAIL_BYTES:
                fh.seek(stat.st_size - TAIL_BYTES)
            title = _last_title(fh.read().decode("utf-8", "replace"))
            if title is None and stat.st_size > TAIL_BYTES:
                fh.seek(0)
                title = _last_title(fh.read().decode("utf-8", "replace"))
    except OSError:
        return None
    _cache[str(path)] = (stat.st_mtime, stat.st_size, title)
    return title


def recent_transcripts(cwd: str, root: Path = DEFAULT_ROOT) -> list[Path]:
    """Top-level transcripts for a cwd, newest first."""
    folder = transcript_dir_for(cwd, root)
    try:
        files = [p for p in folder.glob("*.jsonl") if p.is_file()]
    except OSError:
        return []
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)
