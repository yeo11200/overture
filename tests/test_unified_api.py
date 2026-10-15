"""Unified HTTP API: one board across every hosted project."""
from __future__ import annotations

import asyncio
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from symphony.trackers.file import FileBoardTracker
from symphony.unified.api import build_unified_app
from symphony.unified.supervisor import Supervisor
from tests.test_unified_supervisor import _registry


class LiveOrch:
    def __init__(self, state, running=()):
        self.state = state
        self.dispatch_paused = False
        self._running = list(running)

    async def start(self):
        pass

    async def stop(self):
        pass

    def snapshot(self):
        return {
            "running": [
                {"issue_identifier": ident, "turn_count": 3, "last_event": "turn_completed"}
                for ident in self._running
            ],
            "retrying": [],
        }

    def issue_attention(self, _issue):
        return None


def _ticket(sup: Supervisor, project_id: str, title: str, description: str = "") -> str:
    cfg = sup.get(project_id).cfg
    identifier, _ = FileBoardTracker(cfg.tracker).create_validated(
        identifier=None, title=title, state="Todo", description=description
    )
    return identifier


async def _client(tmp_path, *, running_in_a=("TASK-1",)):
    registry = _registry(tmp_path, ["a", "b"])

    def factory(state):
        project = Path(state.path).parent.name
        return LiveOrch(state, running=running_in_a if project == "a" else ())

    sup = Supervisor(
        registry,
        port=8787,
        factory=factory,
        legacy_running=lambda _wf: False,
        state_path=tmp_path / "unified-state.json",
    )
    await sup.start_all()
    _ticket(sup, "a", "fix login", "body A")
    _ticket(sup, "b", "add chart")
    _ticket(sup, "b", "tune cache")
    client = TestClient(TestServer(build_unified_app(sup, discovery=None)))
    await client.start_server()
    return client, sup


def _run(coro):
    return asyncio.run(coro)


def test_board_merges_projects_and_keeps_same_ids_apart(tmp_path):
    async def go():
        client, _ = await _client(tmp_path)
        try:
            resp = await client.get("/api/v1/unified/board")
            assert resp.status == 200
            data = await resp.json()
        finally:
            await client.close()
        return data

    data = _run(go())
    keys = sorted((c["project_id"], c["identifier"]) for c in data["cards"])
    assert keys == [("a", "TASK-1"), ("b", "TASK-1"), ("b", "TASK-2")]
    live = {(c["project_id"], c["identifier"]): c["live"] for c in data["cards"]}
    assert live[("a", "TASK-1")]["status"] == "running"
    assert live[("a", "TASK-1")]["turn_count"] == 3
    assert live[("b", "TASK-1")] is None
    assert "Todo" in [col["name"] for col in data["columns"]]
    assert {p["id"]: p["status"] for p in data["projects"]} == {"a": "running", "b": "running"}


def test_pause_resume_and_create_and_detail(tmp_path):
    async def go():
        client, sup = await _client(tmp_path)
        try:
            resp = await client.post("/api/v1/unified/projects/b/pause", json={})
            assert resp.status == 200
            assert sup.get("b").orchestrator.dispatch_paused is True

            resp = await client.post(
                "/api/v1/unified/projects/b/issues",
                json={"title": "new from board", "description": "hello"},
            )
            assert resp.status == 201
            created = (await resp.json())["identifier"]

            resp = await client.get(f"/api/v1/unified/projects/b/issues/{created}")
            assert resp.status == 200
            detail = await resp.json()

            resp = await client.post("/api/v1/unified/projects/b/resume", json={})
            assert resp.status == 200
            board = await (await client.get("/api/v1/unified/board")).json()

            resp = await client.post(
                "/api/v1/unified/projects/nope/pause", json={}
            )
            missing_status = resp.status
        finally:
            await client.close()
        return created, detail, board, missing_status

    created, detail, board, missing_status = _run(go())
    assert created == "TASK-3"
    assert detail["title"] == "new from board"
    assert "hello" in detail["description"]
    assert {p["id"]: p["status"] for p in board["projects"]}["b"] == "running"
    assert missing_status == 404


def test_rejects_foreign_host(tmp_path):
    async def go():
        client, _ = await _client(tmp_path)
        try:
            resp = await client.get(
                "/api/v1/unified/board", headers={"Host": "evil.example"}
            )
            return resp.status
        finally:
            await client.close()

    assert _run(go()) == 403


def test_index_serves_unified_page(tmp_path):
    async def go():
        client, _ = await _client(tmp_path)
        try:
            resp = await client.get("/")
            return resp.status, await resp.text()
        finally:
            await client.close()

    status, html = _run(go())
    assert status == 200
    assert "unified.js" in html
