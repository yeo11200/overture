"""Live view of the user's own Claude Code / Codex sessions.

Claude Code hooks POST lifecycle events (prompt submitted, waiting on the
user, stopped, ended); a periodic process scan counts running CLIs per folder
so sessions that never sent an event still show up as "unknown" and sessions
whose process vanished get dropped. Nothing here touches disk.
"""
from __future__ import annotations

import asyncio
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from ..logging import get_logger
from ..projects import Project

log = get_logger()

PROMPT_CHARS = 120
MESSAGE_CHARS = 240
SCAN_INTERVAL_S = 15
AGENT_COMMANDS = {"claude", "codex"}

_STATE_FOR_EVENT = {
    "SessionStart": "idle",
    "UserPromptSubmit": "working",
    "Notification": "waiting",
    "Stop": "done",
}
_STATE_ORDER = {"waiting": 0, "working": 1, "idle": 2, "done": 3}

Group = tuple[str, str, "str | None"]  # (key, display name, project id)


@dataclass
class AgentSession:
    id: str
    cwd: str
    state: str
    prompt: str = ""
    message: str = ""
    updated_at: float = 0.0
    tool: str = "claude"


def parse_lsof_cwds(output: str) -> dict[str, int]:
    """Count processes per cwd from `lsof -Fn -d cwd` field output."""
    counts: dict[str, int] = {}
    for line in output.splitlines():
        if line.startswith("n"):
            counts[line[1:]] = counts.get(line[1:], 0) + 1
    return counts


def scan_processes() -> dict[str, int]:
    """Running claude/codex CLI processes per working directory."""
    ps = subprocess.run(
        ["ps", "-axo", "pid=,comm="], capture_output=True, text=True, check=False
    )
    pids = []
    for line in ps.stdout.splitlines():
        pid, _, comm = line.strip().partition(" ")
        if Path(comm.strip()).name in AGENT_COMMANDS:
            pids.append(pid)
    if not pids:
        return {}
    lsof = subprocess.run(
        ["lsof", "-a", "-d", "cwd", "-Fn", "-p", ",".join(pids)],
        capture_output=True,
        text=True,
        check=False,
    )
    return parse_lsof_cwds(lsof.stdout)


class SessionStore:
    def __init__(
        self,
        projects: Callable[[], Iterable[Project]],
        *,
        watch_root: Path | None,
        ignore_roots: list[Path],
        now: Callable[[], float] = time.time,
    ) -> None:
        self._projects = projects
        self._watch_root = watch_root
        self._ignore = [str(p) for p in ignore_roots]
        self._now = now
        self._sessions: dict[str, AgentSession] = {}
        self._unknown: dict[str, tuple[Group, int]] = {}

    # -- grouping ------------------------------------------------------------

    def _ignored(self, cwd: str) -> bool:
        return cwd in ("", "/") or any(
            cwd == root or cwd.startswith(root + "/") for root in self._ignore
        )

    def _group(self, cwd: str) -> Group:
        best: Project | None = None
        for project in self._projects():
            repo = project.git_repo.rstrip("/")
            if (cwd == repo or cwd.startswith(repo + "/")) and (
                best is None or len(repo) > len(best.git_repo.rstrip("/"))
            ):
                best = project
        if best is not None:
            return best.id, best.name, best.id
        path = Path(cwd)
        root = self._watch_root
        if root is not None and path != root and path.is_relative_to(root):
            name = path.relative_to(root).parts[0]
        else:
            name = path.name or cwd
        return f"folder:{name}", name, None

    # -- updates -------------------------------------------------------------

    def apply(self, event: dict[str, Any]) -> AgentSession | None:
        name = event.get("hook_event_name")
        sid = event.get("session_id")
        cwd = event.get("cwd")
        if not isinstance(sid, str) or not sid or not isinstance(cwd, str):
            return None
        if self._ignored(cwd):
            return None
        if name == "SessionEnd":
            self._sessions.pop(sid, None)
            return None
        state = _STATE_FOR_EVENT.get(str(name))
        if state is None:
            return None
        session = self._sessions.get(sid) or AgentSession(id=sid, cwd=cwd, state=state)
        session.cwd = cwd
        session.state = state
        session.updated_at = self._now()
        session.message = ""
        if name == "UserPromptSubmit":
            prompt = event.get("prompt")
            if isinstance(prompt, str):
                session.prompt = " ".join(prompt.split())[:PROMPT_CHARS]
        elif name == "Notification" and event.get("message"):
            session.message = str(event["message"])[:MESSAGE_CHARS]
        self._sessions[sid] = session
        return session

    def reconcile(self, cwd_counts: dict[str, int]) -> None:
        """Fold a process scan in: unknown counts and vanished sessions."""
        procs: dict[str, tuple[Group, int]] = {}
        for cwd, count in cwd_counts.items():
            if self._ignored(cwd):
                continue
            group = self._group(cwd)
            _, seen = procs.get(group[0], (group, 0))
            procs[group[0]] = (group, seen + count)
        by_group: dict[str, list[AgentSession]] = {}
        for session in self._sessions.values():
            by_group.setdefault(self._group(session.cwd)[0], []).append(session)
        for key, sessions in by_group.items():
            alive = procs[key][1] if key in procs else 0
            # Newest first: sessions beyond the live process count exited
            # without sending SessionEnd.
            sessions.sort(key=lambda s: s.updated_at, reverse=True)
            for gone in sessions[alive:]:
                self._sessions.pop(gone.id, None)
        self._unknown = {
            key: (group, count - len(by_group.get(key, [])))
            for key, (group, count) in procs.items()
            if count > len(by_group.get(key, []))
        }

    # -- read ----------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        groups: dict[str, dict[str, Any]] = {}

        def entry(group: Group) -> dict[str, Any]:
            key, name, project_id = group
            return groups.setdefault(
                key,
                {"key": key, "name": name, "project_id": project_id, "sessions": [], "unknown": 0},
            )

        for session in self._sessions.values():
            entry(self._group(session.cwd))["sessions"].append(
                {
                    "id": session.id,
                    "tool": session.tool,
                    "state": session.state,
                    "prompt": session.prompt,
                    "message": session.message,
                    "cwd": session.cwd,
                    "updated_at": session.updated_at,
                }
            )
        for group, count in self._unknown.values():
            entry(group)["unknown"] = count

        counts = {"working": 0, "waiting": 0, "idle": 0, "done": 0, "unknown": 0}
        for g in groups.values():
            g["sessions"].sort(key=lambda s: (_STATE_ORDER[s["state"]], -s["updated_at"]))
            for s in g["sessions"]:
                counts[s["state"]] += 1
            counts["unknown"] += g["unknown"]

        def rank(g: dict[str, Any]) -> tuple[int, str]:
            best = min(
                (_STATE_ORDER[s["state"]] for s in g["sessions"]), default=len(_STATE_ORDER)
            )
            return best, g["name"]

        return {"groups": sorted(groups.values(), key=rank), "counts": counts}

    async def run_scanner(self, interval_s: float = SCAN_INTERVAL_S) -> None:
        while True:
            try:
                self.reconcile(await asyncio.to_thread(scan_processes))
            except Exception as exc:
                log.warning("unified_session_scan_failed", error=str(exc))
            await asyncio.sleep(interval_s)
