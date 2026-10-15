"""Unified supervisor: one process hosting every registered project."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from symphony.projects import Project, ProjectRegistry
from symphony.service import unified_owner_pid
from symphony.unified.supervisor import Supervisor


def _workflow(repo: Path, *, tracker: str = "file") -> Path:
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "kanban").mkdir(exist_ok=True)
    extra = (
        "endpoint: https://api.linear.app/graphql, api_key: x, project_slug: p,"
        if tracker == "linear"
        else "board_root: ./kanban,"
    )
    path = repo / "WORKFLOW.md"
    path.write_text(
        "---\n"
        f"tracker: {{ kind: {tracker}, {extra} active_states: [Todo], terminal_states: [Done] }}\n"
        f"workspace: {{ root: {repo}/ws }}\n"
        "agent: { kind: codex }\n"
        "codex: { command: python -m symphony.mock_codex }\n"
        "---\nhi\n"
    )
    return path


def _registry(tmp_path: Path, names: list[str], **kw) -> ProjectRegistry:
    registry = ProjectRegistry(tmp_path / "projects.json")
    projects = []
    for i, name in enumerate(names):
        wf = _workflow(tmp_path / name, **kw.get(name, {}))
        projects.append(
            Project(
                id=name,
                name=name,
                git_repo=str(wf.parent),
                workflow=str(wf),
                host="127.0.0.1",
                port=10000 + i,
            )
        )
    registry.save(projects)
    return registry


class FakeOrch:
    def __init__(self, state, fail: bool = False):
        self.state = state
        self.fail = fail
        self.started = False
        self.stopped = False
        self.dispatch_paused = False

    async def start(self):
        if self.fail:
            raise RuntimeError("boom")
        self.started = True

    async def stop(self):
        self.stopped = True


def _supervisor(tmp_path, registry, *, failing=(), legacy=()):
    made: dict[str, FakeOrch] = {}

    def factory(state):
        project = Path(state.path).parent.name
        orch = FakeOrch(state, fail=project in failing)
        made[project] = orch
        return orch

    sup = Supervisor(
        registry,
        port=8787,
        factory=factory,
        legacy_running=lambda wf: Path(wf).parent.name in legacy,
        state_path=tmp_path / "unified-state.json",
    )
    return sup, made


def _status(sup) -> dict[str, str]:
    return {rt.project.id: rt.status for rt in sup.runtimes()}


def test_one_failing_project_does_not_stop_others(tmp_path):
    registry = _registry(tmp_path, ["a", "b", "c"])
    sup, made = _supervisor(tmp_path, registry, failing={"b"})
    asyncio.run(sup.start_all())
    assert _status(sup) == {"a": "running", "b": "error", "c": "running"}
    assert made["a"].started and made["c"].started


def test_legacy_service_is_conflict_and_not_started(tmp_path):
    registry = _registry(tmp_path, ["a", "b"])
    sup, made = _supervisor(tmp_path, registry, legacy={"b"})
    asyncio.run(sup.start_all())
    assert _status(sup) == {"a": "running", "b": "conflict"}
    assert "b" not in made


def test_non_file_tracker_is_unsupported(tmp_path):
    registry = _registry(tmp_path, ["a", "lin"], lin={"tracker": "linear"})
    sup, made = _supervisor(tmp_path, registry)
    asyncio.run(sup.start_all())
    assert _status(sup)["lin"] == "unsupported"
    assert "lin" not in made


def test_missing_workflow_is_missing(tmp_path):
    registry = _registry(tmp_path, ["a", "gone"])
    (tmp_path / "gone" / "WORKFLOW.md").unlink()
    sup, _ = _supervisor(tmp_path, registry)
    asyncio.run(sup.start_all())
    assert _status(sup)["gone"] == "missing"


def test_pause_sets_flag_and_persists(tmp_path):
    registry = _registry(tmp_path, ["a", "b"])
    sup, made = _supervisor(tmp_path, registry)
    asyncio.run(sup.start_all())
    sup.set_paused("a", True)
    assert made["a"].dispatch_paused is True
    assert _status(sup)["a"] == "paused"
    assert json.loads((tmp_path / "unified-state.json").read_text())["paused"] == ["a"]

    sup2, made2 = _supervisor(tmp_path, registry)
    asyncio.run(sup2.start_all())
    assert made2["a"].dispatch_paused is True
    assert _status(sup2)["b"] == "running"


def test_marker_claims_project_until_stop(tmp_path):
    registry = _registry(tmp_path, ["a"])
    sup, made = _supervisor(tmp_path, registry)
    wf = tmp_path / "a" / "WORKFLOW.md"
    asyncio.run(sup.start_all())
    assert unified_owner_pid(wf) == os.getpid()
    asyncio.run(sup.stop_all())
    assert made["a"].stopped
    assert unified_owner_pid(wf) is None
