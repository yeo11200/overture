"""User annotations for the session graph: roles, threads and dependency arrows.

Stored as one small JSON file keyed by Claude Code session id. Prompts and
other session content never land here.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

ROLES = ("main", "plan", "implement", "review", "experiment")
THREAD_CHARS = 40


class GraphError(ValueError):
    """A rejected annotation (unknown role, cycle, self edge)."""


class GraphNotes:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._sessions: dict[str, dict[str, str]] = {}
        self._edges: list[tuple[str, str]] = []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self._sessions = {
                str(k): {kk: str(vv) for kk, vv in v.items() if kk in ("role", "thread")}
                for k, v in data.get("sessions", {}).items()
                if isinstance(v, dict)
            }
            self._edges = [(str(a), str(b)) for a, b in data.get("edges", [])]
        except (OSError, ValueError, AttributeError, TypeError):
            pass

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_name(self._path.name + ".tmp")
        tmp.write_text(
            json.dumps(
                {"sessions": self._sessions, "edges": [list(e) for e in self._edges]},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        tmp.replace(self._path)

    # -- reads -----------------------------------------------------------------

    def notes_for(self, session_id: str) -> dict[str, str]:
        return dict(self._sessions.get(session_id, {}))

    def edges(self, alive: Iterable[str] | None = None) -> list[tuple[str, str]]:
        if alive is None:
            return list(self._edges)
        ids = set(alive)
        return [e for e in self._edges if e[0] in ids and e[1] in ids]

    # -- writes ----------------------------------------------------------------

    def annotate(self, session_id: str, *, role: Any = None, thread: Any = None) -> dict[str, str]:
        notes = self._sessions.setdefault(session_id, {})
        if role is not None:
            if role not in ROLES and role != "":
                raise GraphError(f"role must be one of {', '.join(ROLES)}")
            notes["role"] = role
        if thread is not None:
            if not isinstance(thread, str):
                raise GraphError("thread must be a string")
            notes["thread"] = " ".join(thread.split())[:THREAD_CHARS]
        cleaned = {k: v for k, v in notes.items() if v}
        if cleaned:
            self._sessions[session_id] = cleaned
        else:
            self._sessions.pop(session_id, None)
        self._save()
        return dict(cleaned)

    def _reaches(self, start: str, goal: str) -> bool:
        seen, stack = set(), [start]
        while stack:
            node = stack.pop()
            if node == goal:
                return True
            if node in seen:
                continue
            seen.add(node)
            stack.extend(b for a, b in self._edges if a == node)
        return False

    def add_edge(self, source: str, target: str) -> None:
        if source == target:
            raise GraphError("an agent cannot depend on itself")
        if (source, target) in self._edges:
            return
        if self._reaches(target, source):
            raise GraphError("that arrow would make a cycle")
        self._edges.append((source, target))
        self._save()

    def remove_edge(self, source: str, target: str) -> bool:
        if (source, target) not in self._edges:
            return False
        self._edges.remove((source, target))
        self._save()
        return True

    def prune(self, alive: Iterable[str]) -> bool:
        """Forget notes and arrows of sessions that no longer exist."""
        ids = set(alive)
        sessions = {k: v for k, v in self._sessions.items() if k in ids}
        edges = [e for e in self._edges if e[0] in ids and e[1] in ids]
        if sessions == self._sessions and edges == self._edges:
            return False
        self._sessions, self._edges = sessions, edges
        self._save()
        return True
