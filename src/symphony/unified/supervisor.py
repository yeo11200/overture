"""Run every registered project's orchestrator inside one event loop.

Each project keeps its own WORKFLOW.md, state.db and workspaces; only the
process and the HTTP port are shared. A failure in one project is recorded on
its runtime and never stops the others.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..logging import get_logger
from ..orchestrator import Orchestrator
from ..projects import Project, ProjectRegistry, projects_file
from ..service import (
    clear_unified_marker,
    service_status,
    write_unified_marker,
)
from ..workflow import ServiceConfig, WorkflowState

log = get_logger()

OrchestratorFactory = Callable[[WorkflowState], Any]


def _default_factory(state: WorkflowState) -> Orchestrator:
    return Orchestrator(state, isolated_env=True)


def _legacy_service_running(workflow: str) -> bool:
    return service_status(workflow).state == "running"


@dataclass
class ProjectRuntime:
    project: Project
    status: str = "starting"  # running|paused|error|conflict|missing|unsupported
    error: str | None = None
    orchestrator: Any = None
    cfg: ServiceConfig | None = None


class Supervisor:
    def __init__(
        self,
        registry: ProjectRegistry,
        *,
        port: int,
        factory: OrchestratorFactory = _default_factory,
        legacy_running: Callable[[str], bool] = _legacy_service_running,
        state_path: Path | None = None,
    ) -> None:
        self._registry = registry
        self._port = port
        self._factory = factory
        self._legacy_running = legacy_running
        self._state_path = state_path or projects_file().parent / "unified-state.json"
        self._paused = self._load_paused()
        self._runtimes: dict[str, ProjectRuntime] = {}

    # -- persistence -------------------------------------------------------

    def _load_paused(self) -> set[str]:
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
            return {str(item) for item in data.get("paused", [])}
        except (OSError, ValueError, AttributeError):
            return set()

    def _save_paused(self) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(
            json.dumps({"paused": sorted(self._paused)}) + "\n", encoding="utf-8"
        )

    # -- lifecycle ---------------------------------------------------------

    async def start_all(self) -> None:
        for project in self._registry.list():
            await self.ensure(project)

    async def ensure(self, project: Project) -> ProjectRuntime:
        """Start one project if it is not hosted yet. Never raises."""
        existing = self._runtimes.get(project.id)
        if existing is not None and existing.orchestrator is not None:
            return existing
        runtime = ProjectRuntime(project=project)
        self._runtimes[project.id] = runtime
        workflow = Path(project.workflow)
        if not workflow.is_file():
            runtime.status = "missing"
            return runtime
        state = WorkflowState(workflow)
        cfg, err = state.reload()
        if cfg is None:
            runtime.status, runtime.error = "error", str(err)
            return runtime
        runtime.cfg = cfg
        if cfg.tracker.kind != "file":
            runtime.status = "unsupported"
            return runtime
        if self._legacy_running(str(workflow)):
            runtime.status = "conflict"
            runtime.error = "a per-project `symphony service` already runs this workflow"
            return runtime
        try:
            orchestrator = self._factory(state)
            orchestrator.dispatch_paused = project.id in self._paused
            await orchestrator.start()
        except Exception as exc:
            log.warning("unified_project_start_failed", project=project.id, error=str(exc))
            runtime.status, runtime.error = "error", str(exc)
            return runtime
        runtime.orchestrator = orchestrator
        runtime.status = "paused" if orchestrator.dispatch_paused else "running"
        write_unified_marker(workflow, pid=os.getpid(), port=self._port)
        log.info("unified_project_started", project=project.id)
        return runtime

    async def stop_all(self) -> None:
        for runtime in self._runtimes.values():
            if runtime.orchestrator is None:
                continue
            try:
                await runtime.orchestrator.stop()
            except Exception as exc:
                log.warning("unified_project_stop_failed", project=runtime.project.id, error=str(exc))
            clear_unified_marker(runtime.project.workflow)
            runtime.orchestrator = None

    # -- queries / controls -----------------------------------------------

    def runtimes(self) -> list[ProjectRuntime]:
        for runtime in self._runtimes.values():
            task = getattr(runtime.orchestrator, "_tick_task", None)
            if task is not None and task.done():
                runtime.status = "error"
                runtime.error = runtime.error or "orchestrator tick loop stopped"
        return list(self._runtimes.values())

    def get(self, project_id: str) -> ProjectRuntime | None:
        return self._runtimes.get(project_id)

    def set_paused(self, project_id: str, paused: bool) -> ProjectRuntime:
        runtime = self._runtimes[project_id]
        if paused:
            self._paused.add(project_id)
        else:
            self._paused.discard(project_id)
        self._save_paused()
        if runtime.orchestrator is not None:
            runtime.orchestrator.dispatch_paused = paused
            runtime.status = "paused" if paused else "running"
        return runtime
