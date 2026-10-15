"""Live view of the user's own Claude Code / Codex sessions.

Claude Code hooks POST lifecycle events (prompt submitted, waiting on the
user, stopped, ended); a periodic process scan counts running CLIs per folder
so sessions that never sent an event still show up, named from their Claude
Code transcript when one can be matched. Sessions group by git repository, so
a worktree lands under the project it belongs to. Nothing here touches disk
except reading transcripts.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from ..logging import get_logger
from ..projects import Project
from .codex_titles import codex_title
from .titles import DEFAULT_ROOT, recent_transcripts, title_from_transcript

log = get_logger()

PROMPT_CHARS = 120
MESSAGE_CHARS = 240
SCAN_INTERVAL_S = 5
ORCA_FALLBACK = Path("/Applications/Orca.app/Contents/Resources/bin/orca")
IDLE_GLYPH = "✳"  # Claude Code's tab title prefix when idle; a spinner while working
REPO_CACHE_S = 60
AGENT_COMMANDS = {"claude", "codex"}

# Claude Code and Codex share these hook event names.
_STATE_FOR_EVENT = {
    "SessionStart": "idle",
    "UserPromptSubmit": "working",
    "PreToolUse": "working",  # an approved request resumes work
    "Notification": "waiting",
    "PermissionRequest": "waiting",
    "Stop": "done",
    "Interrupt": "done",
}
_STATE_ORDER = {"waiting": 0, "working": 1, "idle": 2, "done": 3, "unknown": 4}

Group = tuple[str, str, "str | None"]  # (key, display name, project id)
RepoInfo = Callable[[str], "tuple[str | None, str | None]"]


@dataclass
class AgentSession:
    id: str
    cwd: str
    state: str
    prompt: str = ""
    message: str = ""
    title: str = ""
    updated_at: float = 0.0
    tool: str = "claude"
    branch: str | None = None


# -- process scan ---------------------------------------------------------------


def parse_lsof_cwds(output: str) -> dict[str, int]:
    """Count processes per cwd from `lsof -Fn -d cwd` field output."""
    counts: dict[str, int] = {}
    for line in output.splitlines():
        if line.startswith("n"):
            counts[line[1:]] = counts.get(line[1:], 0) + 1
    return counts


def parse_lsof_pids(output: str) -> dict[str, str]:
    """pid -> cwd from `lsof -Fn -d cwd` field output."""
    result: dict[str, str] = {}
    pid = None
    for line in output.splitlines():
        if line.startswith("p"):
            pid = line[1:]
        elif line.startswith("n") and pid is not None:
            result[pid] = line[1:]
    return result


def scan_processes() -> dict[str, dict[str, int]]:
    """Running agent CLIs as {tool: {cwd: count}}."""
    ps = subprocess.run(
        ["ps", "-axo", "pid=,comm="], capture_output=True, text=True, check=False
    )
    tools: dict[str, str] = {}
    for line in ps.stdout.splitlines():
        pid, _, comm = line.strip().partition(" ")
        name = Path(comm.strip()).name
        if name in AGENT_COMMANDS:
            tools[pid] = name
    result: dict[str, dict[str, int]] = {tool: {} for tool in AGENT_COMMANDS}
    if not tools:
        return result
    lsof = subprocess.run(
        ["lsof", "-a", "-d", "cwd", "-Fn", "-p", ",".join(tools)],
        capture_output=True,
        text=True,
        check=False,
    )
    for pid, cwd in parse_lsof_pids(lsof.stdout).items():
        per_tool = result[tools.get(pid, "claude")]
        per_tool[cwd] = per_tool.get(cwd, 0) + 1
    return result


# -- Orca terminals ---------------------------------------------------------------


def parse_orca_terminals(payload: Any) -> list[dict[str, Any]]:
    """Agent terminals from `orca terminal list --json`, titles as shown on tabs."""
    result = payload.get("result") if isinstance(payload, dict) else None
    terminals = result.get("terminals") if isinstance(result, dict) else result
    found = []
    for t in terminals or []:
        tool = t.get("agentIdentity")
        if tool not in AGENT_COMMANDS or not t.get("connected", True):
            continue
        title = str(t.get("title") or "").strip()
        state = "unknown"
        head, _, rest = title.partition(" ")
        if tool == "claude" and rest and len(head) <= 2 and not head[0].isalnum():
            state = "idle" if head == IDLE_GLYPH else "working"
            title = rest.strip()
        if " | " in title:  # codex tabs read "<title> | <folder>"
            title = title.rsplit(" | ", 1)[0].strip()
        found.append(
            {
                "handle": str(t.get("handle")),
                "tool": tool,
                "title": title,
                "state": state,
                "path": str(t.get("worktreePath") or ""),
                "branch": str(t.get("branch") or "").removeprefix("refs/heads/") or None,
                "last_output": (t.get("lastOutputAt") or 0) / 1000,
            }
        )
    return found


def scan_orca() -> list[dict[str, Any]] | None:
    """Orca's agent terminals, or None when Orca is not available."""
    exe = shutil.which("orca") or (str(ORCA_FALLBACK) if ORCA_FALLBACK.exists() else None)
    if exe is None:
        return None
    try:
        out = subprocess.run(
            [exe, "terminal", "list", "--json"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        return parse_orca_terminals(json.loads(out.stdout)) if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


# -- git ------------------------------------------------------------------------

_repo_cache: dict[str, tuple[float, str | None, str | None]] = {}


def git_repo_info(cwd: str) -> tuple[str | None, str | None]:
    """(main repository root, current branch) for a cwd; worktrees resolve to
    the repository they were added from. Cached for a minute."""
    now = time.monotonic()
    cached = _repo_cache.get(cwd)
    if cached and now - cached[0] < REPO_CACHE_S:
        return cached[1], cached[2]
    root = branch = None
    try:
        out = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--path-format=absolute",
             "--git-common-dir", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=3, check=False,
        )
        lines = out.stdout.split()
        if out.returncode == 0 and len(lines) >= 2:
            common = Path(lines[0])
            root = str(common.parent if common.name == ".git" else common)
            branch = None if lines[1] == "HEAD" else lines[1]
    except (OSError, subprocess.SubprocessError):
        pass
    _repo_cache[cwd] = (now, root, branch)
    return root, branch


class SessionStore:
    def __init__(
        self,
        projects: Callable[[], Iterable[Project]],
        *,
        watch_root: Path | None,
        ignore_roots: list[Path],
        now: Callable[[], float] = time.time,
        repo_info: RepoInfo = git_repo_info,
        transcripts_root: Path = DEFAULT_ROOT,
    ) -> None:
        self._projects = projects
        self._watch_root = watch_root
        self._ignore = [str(p) for p in ignore_roots]
        self._now = now
        self._repo_info = repo_info
        self._transcripts = transcripts_root
        self._sessions: dict[str, AgentSession] = {}
        self._inferred: list[AgentSession] = []
        self._orca: list[dict[str, Any]] | None = None

    # -- grouping ------------------------------------------------------------

    def _ignored(self, cwd: str) -> bool:
        return cwd in ("", "/") or any(
            cwd == root or cwd.startswith(root + "/") for root in self._ignore
        )

    def _folder(self, cwd: str) -> str:
        path = Path(cwd)
        root = self._watch_root
        if root is not None and path != root and path.is_relative_to(root):
            return path.relative_to(root).parts[0]
        return path.name or cwd

    def _group(self, cwd: str) -> Group:
        repo_root, _ = self._repo_info(cwd)
        projects = list(self._projects())
        if repo_root is not None:
            for project in projects:
                if project.git_repo.rstrip("/") == repo_root.rstrip("/"):
                    return project.id, project.name, project.id
        best: Project | None = None
        for project in projects:
            repo = project.git_repo.rstrip("/")
            if (cwd == repo or cwd.startswith(repo + "/")) and (
                best is None or len(repo) > len(best.git_repo.rstrip("/"))
            ):
                best = project
        if best is not None:
            return best.id, best.name, best.id
        name = Path(repo_root).name if repo_root else self._folder(cwd)
        return f"folder:{name}", name, None

    # -- updates -------------------------------------------------------------

    def apply(self, event: dict[str, Any], tool: str = "claude") -> AgentSession | None:
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
        session = self._sessions.get(sid) or AgentSession(id=sid, cwd=cwd, state=state, tool=tool)
        session.tool = tool
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
        elif name == "PermissionRequest":
            tool_input = event.get("tool_input")
            detail = tool_input.get("description") if isinstance(tool_input, dict) else None
            asked = detail or event.get("tool_name") or "a tool"
            session.message = f"승인 요청: {asked}"[:MESSAGE_CHARS]
        if tool == "codex":
            session.title = codex_title(sid) or session.title
        else:
            transcript = event.get("transcript_path")
            if isinstance(transcript, str) and Path(transcript).is_relative_to(self._transcripts):
                session.title = title_from_transcript(Path(transcript)) or session.title
        self._sessions[sid] = session
        return session

    def reconcile(
        self, cwd_counts: dict[str, int], codex_counts: dict[str, int] | None = None
    ) -> None:
        """Fold a process scan in: vanished sessions, named and anonymous unknowns."""
        procs: dict[str, tuple[Group, int, list[str]]] = {}
        for cwd, count in cwd_counts.items():
            if self._ignored(cwd):
                continue
            group = self._group(cwd)
            _, seen, cwds = procs.get(group[0], (group, 0, []))
            procs[group[0]] = (group, seen + count, [*cwds, cwd])
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

        inferred: list[AgentSession] = []
        for key, (group, count, cwds) in procs.items():
            missing = count - len(by_group.get(key, []))
            if missing <= 0:
                continue
            # Name the unknowns after the newest transcripts of their folders.
            candidates = sorted(
                ((p, cwd) for cwd in cwds for p in recent_transcripts(cwd, self._transcripts)),
                key=lambda pc: pc[0].stat().st_mtime,
                reverse=True,
            )
            for path, cwd in candidates:
                if missing == 0:
                    break
                if path.stem in self._sessions:
                    continue
                inferred.append(
                    AgentSession(
                        id=path.stem,
                        cwd=cwd,
                        state="unknown",
                        title=title_from_transcript(path) or "",
                        updated_at=path.stat().st_mtime,
                    )
                )
                missing -= 1
            # Still unnamed: one card per process anyway, never a lump.
            for i in range(missing):
                inferred.append(AgentSession(id=f"proc:{cwds[0]}:{i}", cwd=cwds[0], state="unknown"))

        for cwd, count in (codex_counts or {}).items():
            if self._ignored(cwd):
                continue
            for i in range(count):
                inferred.append(
                    AgentSession(id=f"codex:{cwd}:{i}", cwd=cwd, state="unknown", tool="codex")
                )
        self._inferred = inferred

    def set_orca(self, terminals: list[dict[str, Any]] | None) -> None:
        """Orca's terminal list becomes the source of truth for what runs."""
        self._orca = terminals

    def _orca_cards(self) -> list[AgentSession]:
        assert self._orca is not None
        hooks = list(self._sessions.values())
        used: set[str] = set()

        def inside(cwd: str, path: str) -> bool:
            return bool(path) and (cwd == path or cwd.startswith(path + "/"))

        # Untitled sessions pair with the tab whose folder is nearest to their
        # cwd, so a session in ~/code/app never lands on a tab opened at ~/code.
        nearest: dict[str, AgentSession] = {}
        for h in hooks:
            if h.title:
                continue
            terms = [t for t in self._orca if inside(h.cwd, t["path"]) and t["handle"] not in nearest]
            if terms:
                nearest[max(terms, key=lambda t: len(t["path"]))["handle"]] = h

        def match(term: dict[str, Any]) -> AgentSession | None:
            for h in hooks:  # Claude names the tab after the session title
                if h.id not in used and h.title and h.title == term["title"]:
                    return h
            h = nearest.get(term["handle"])
            return h if h is not None and h.id not in used else None

        cards = []
        for term in self._orca:
            if self._ignored(term["path"]):
                continue
            hook = match(term)
            if hook is not None:
                used.add(hook.id)
            if hook is not None and hook.state == "waiting":
                state = "waiting"
            elif term["state"] != "unknown":
                state = "done" if term["state"] == "idle" and hook and hook.state == "done" else term["state"]
            else:
                state = hook.state if hook else "unknown"
            cards.append(
                AgentSession(
                    id=term["handle"],
                    cwd=term["path"],
                    state=state,
                    title=term["title"],
                    prompt=hook.prompt if hook else "",
                    message=hook.message if hook else "",
                    updated_at=max(term["last_output"], hook.updated_at if hook else 0),
                    tool=term["tool"],
                    branch=term["branch"],
                )
            )
        # Sessions running outside Orca still show from their hook events.
        cards += [h for h in hooks if h.id not in used]
        return cards

    def _cards(self) -> list[AgentSession]:
        if self._orca is not None:
            return self._orca_cards()
        return [*self._sessions.values(), *self._inferred]

    def alive_ids(self) -> set[str]:
        return {c.id for c in self._cards()}

    # -- read ----------------------------------------------------------------

    def _session_json(self, session: AgentSession) -> dict[str, Any]:
        branch = session.branch or self._repo_info(session.cwd)[1]
        return {
            "id": session.id,
            "tool": session.tool,
            "state": session.state,
            "title": session.title,
            "folder": self._folder(session.cwd),
            "branch": branch,
            "prompt": session.prompt,
            "message": session.message,
            "cwd": session.cwd,
            "updated_at": session.updated_at,
        }

    def snapshot(self) -> dict[str, Any]:
        groups: dict[str, dict[str, Any]] = {}

        def entry(group: Group) -> dict[str, Any]:
            key, name, project_id = group
            return groups.setdefault(
                key,
                {"key": key, "name": name, "project_id": project_id, "sessions": []},
            )

        for session in self._cards():
            entry(self._group(session.cwd))["sessions"].append(self._session_json(session))

        counts = {state: 0 for state in _STATE_ORDER}
        for g in groups.values():
            g["sessions"].sort(key=lambda s: (_STATE_ORDER[s["state"]], -s["updated_at"]))
            for s in g["sessions"]:
                counts[s["state"]] += 1

        def rank(g: dict[str, Any]) -> tuple[int, str]:
            best = min(
                (_STATE_ORDER[s["state"]] for s in g["sessions"]), default=len(_STATE_ORDER)
            )
            return best, g["name"]

        return {"groups": sorted(groups.values(), key=rank), "counts": counts}

    async def run_scanner(
        self,
        interval_s: float = SCAN_INTERVAL_S,
        on_scan: Callable[[set[str]], object] | None = None,
    ) -> None:
        while True:
            try:
                scan = await asyncio.to_thread(scan_processes)
                self.reconcile(scan.get("claude", {}), scan.get("codex", {}))
                self.set_orca(await asyncio.to_thread(scan_orca))
                if on_scan is not None:
                    on_scan(self.alive_ids())
            except Exception as exc:
                log.warning("unified_session_scan_failed", error=str(exc))
            await asyncio.sleep(interval_s)
