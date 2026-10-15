"""Unified discovery: auto-register new git repositories under a watch root."""
from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

from symphony.projects import Project, ProjectRegistry
from symphony.unified.discovery import Discovery


def _git(path: Path) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return path


class FakeSupervisor:
    def __init__(self):
        self.ensured: list[str] = []

    async def ensure(self, project):
        self.ensured.append(project.id)


def _discovery(tmp_path, root, registry, *, adopt, exclude=()):
    sup = FakeSupervisor()
    disc = Discovery(
        root,
        registry=registry,
        supervisor=sup,
        exclude=set(exclude),
        failures_path=tmp_path / "failures.json",
        adopt=adopt,
    )
    return disc, sup


def test_registers_only_new_plain_git_repos(tmp_path):
    root = tmp_path / "root"
    new = _git(root / "new-app")
    known = _git(root / "known")
    _git(root / "skipme")
    (root / "notes").mkdir()
    (root / "wt").mkdir()
    (root / "wt" / ".git").write_text("gitdir: /elsewhere\n")
    registry = ProjectRegistry(tmp_path / "projects.json")
    registry.save(
        [Project("known", "known", str(known), str(known / "WORKFLOW.md"), "127.0.0.1", 10000)]
    )
    adopted: list[Path] = []

    def adopt(target, **kw):
        adopted.append(Path(target))
        project = Project(
            kw["name"], kw["name"], str(target), str(Path(target) / "WORKFLOW.md"), "127.0.0.1", 10001
        )
        registry.save([*registry.list(), project])
        return project

    disc, sup = _discovery(tmp_path, root, registry, adopt=adopt, exclude={"skipme"})
    added = asyncio.run(disc.scan_once())
    assert adopted == [new]
    assert added == ["new-app"]
    assert sup.ensured == ["new-app"]


def test_failure_is_recorded_and_not_retried(tmp_path):
    root = tmp_path / "root"
    _git(root / "broken")
    registry = ProjectRegistry(tmp_path / "projects.json")
    calls: list[str] = []

    def adopt(target, **kw):
        calls.append(kw["name"])
        raise RuntimeError("pathspec 'docs/x' did not match")

    disc, sup = _discovery(tmp_path, root, registry, adopt=adopt)
    asyncio.run(disc.scan_once())
    asyncio.run(disc.scan_once())
    assert calls == ["broken"]
    failures = json.loads((tmp_path / "failures.json").read_text())
    assert "pathspec" in failures[str(root / "broken")]["error"]
    assert sup.ensured == []

    disc.retry(str(root / "broken"))
    asyncio.run(disc.scan_once())
    assert calls == ["broken", "broken"]
