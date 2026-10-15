"""Auto-register new git repositories that appear under a watch root.

Runs inside the unified server (a user process), so it has the same folder
access as the terminal that started it — unlike a launchd agent, which macOS
TCC blocks from ~/Documents.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..logging import get_logger
from ..projects import ProjectRegistry, create_or_adopt_project, source_checkout

log = get_logger()

SCAN_INTERVAL_S = 300


def _default_adopt(target: Path, **kw: Any):
    return create_or_adopt_project(target, source=source_checkout(), **kw)


class Discovery:
    def __init__(
        self,
        root: Path,
        *,
        registry: ProjectRegistry,
        supervisor: Any,
        exclude: set[str],
        failures_path: Path,
        adopt: Callable[..., Any] = _default_adopt,
    ) -> None:
        self.root = root.expanduser()
        self._registry = registry
        self._supervisor = supervisor
        self._exclude = exclude
        self._failures_path = failures_path
        self._adopt = adopt

    def failures(self) -> dict[str, dict[str, str]]:
        try:
            data = json.loads(self._failures_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_failures(self, failures: dict[str, dict[str, str]]) -> None:
        self._failures_path.parent.mkdir(parents=True, exist_ok=True)
        self._failures_path.write_text(
            json.dumps(failures, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    def retry(self, path: str) -> None:
        failures = self.failures()
        failures.pop(path, None)
        self._save_failures(failures)

    def _candidates(self) -> list[Path]:
        registered = {Path(p.git_repo).resolve() for p in self._registry.list()}
        failed = set(self.failures())
        found = []
        for child in sorted(self.root.iterdir()):
            if (
                child.is_dir()
                and (child / ".git").is_dir()  # a `.git` file means a worktree
                and child.name not in self._exclude
                and child.resolve() not in registered
                and str(child) not in failed
            ):
                found.append(child)
        return found

    async def scan_once(self) -> list[str]:
        added: list[str] = []
        try:
            candidates = self._candidates()
        except OSError as exc:
            log.warning("unified_discovery_scan_failed", root=str(self.root), error=str(exc))
            return added
        for path in candidates:
            try:
                project = await asyncio.to_thread(self._adopt, path, name=path.name)
            except Exception as exc:
                failures = self.failures()
                failures[str(path)] = {
                    "error": str(exc),
                    "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
                self._save_failures(failures)
                log.warning("unified_discovery_adopt_failed", path=str(path), error=str(exc))
                continue
            await self._supervisor.ensure(project)
            added.append(project.id)
            log.info("unified_discovery_added", project=project.id)
        return added

    async def run(self, interval_s: float = SCAN_INTERVAL_S) -> None:
        while True:
            await self.scan_once()
            await asyncio.sleep(interval_s)
