"""Codex session titles from Codex's local state database (read-only).

Codex keeps threads in `~/.codex/state_<n>.sqlite`; `threads.name` is the
name shown on terminal tabs and `threads.title` the first-message fallback.
The database is opened with `mode=ro`, so nothing is ever written.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

CODEX_HOME = Path.home() / ".codex"
CACHE_S = 30

_cache: dict[str, tuple[float, str | None]] = {}


def _database(home: Path) -> Path | None:
    candidates = sorted(home.glob("state_*.sqlite"), key=lambda p: p.stat().st_mtime)
    return candidates[-1] if candidates else None


def codex_title(session_id: str, home: Path = CODEX_HOME) -> str | None:
    now = time.monotonic()
    cached = _cache.get(session_id)
    if cached and now - cached[0] < CACHE_S:
        return cached[1]
    title = None
    db = _database(home)
    if db is not None:
        try:
            with sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=1) as conn:
                row = conn.execute(
                    "select name, title from threads where id = ?", (session_id,)
                ).fetchone()
            if row:
                title = (row[0] or row[1] or "").strip() or None
        except sqlite3.Error:
            title = None
    _cache[session_id] = (now, title)
    return title
