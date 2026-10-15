"""Unified HTTP API: one board across every hosted project."""
from __future__ import annotations

import asyncio
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from symphony.trackers.file import FileBoardTracker
from symphony.unified.api import build_unified_app
from symphony.unified.graph import GraphNotes
from symphony.unified.sessions import SessionStore
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
    sessions = SessionStore(
        lambda: [rt.project for rt in sup.runtimes()], watch_root=tmp_path, ignore_roots=[]
    )
    client = TestClient(
        TestServer(
            build_unified_app(
                sup, discovery=None, sessions=sessions,
                graph=GraphNotes(tmp_path / "graph.json"),
            )
        )
    )
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


def test_session_events_show_up_grouped_by_project(tmp_path):
    async def go():
        client, _ = await _client(tmp_path)
        try:
            for event in (
                {"hook_event_name": "UserPromptSubmit", "session_id": "s1",
                 "cwd": str(tmp_path / "a" / "src"), "prompt": "fix the login bug"},
                {"hook_event_name": "Notification", "session_id": "s2",
                 "cwd": str(tmp_path / "loose"), "message": "needs permission"},
            ):
                resp = await client.post("/api/v1/unified/sessions/events", json=event)
                assert resp.status == 200
            return await (await client.get("/api/v1/unified/sessions")).json()
        finally:
            await client.close()

    data = _run(go())
    groups = {g["key"]: g for g in data["groups"]}
    assert groups["a"]["sessions"][0]["state"] == "working"
    assert groups["a"]["sessions"][0]["prompt"] == "fix the login bug"
    assert groups["folder:loose"]["sessions"][0]["state"] == "waiting"
    assert data["groups"][0]["key"] == "folder:loose"
    assert data["counts"]["waiting"] == 1


def test_roles_threads_and_edges_round_trip(tmp_path):
    async def go():
        client, _ = await _client(tmp_path)
        try:
            for sid in ("impl", "rev"):
                await client.post("/api/v1/unified/sessions/events", json={
                    "hook_event_name": "UserPromptSubmit", "session_id": sid,
                    "cwd": str(tmp_path / "a"), "prompt": sid})
            r1 = await client.patch("/api/v1/unified/sessions/rev",
                                    json={"role": "review", "thread": "minor units"})
            bad_role = await client.patch("/api/v1/unified/sessions/rev", json={"role": "boss"})
            ghost = await client.patch("/api/v1/unified/sessions/ghost", json={"role": "main"})
            e1 = await client.post("/api/v1/unified/sessions/edges", json={"from": "impl", "to": "rev"})
            cycle = await client.post("/api/v1/unified/sessions/edges", json={"from": "rev", "to": "impl"})
            listed = await (await client.get("/api/v1/unified/sessions")).json()
            d1 = await client.delete("/api/v1/unified/sessions/edges", json={"from": "impl", "to": "rev"})
            after = await (await client.get("/api/v1/unified/sessions")).json()
            return (r1.status, bad_role.status, ghost.status, e1.status, cycle.status,
                    listed, await d1.json(), after)
        finally:
            await client.close()

    r1, bad_role, ghost, e1, cycle, listed, d1, after = _run(go())
    assert (r1, bad_role, ghost, e1, cycle) == (200, 400, 404, 201, 409)
    rev = next(s for g in listed["groups"] for s in g["sessions"] if s["id"] == "rev")
    assert rev["role"] == "review" and rev["thread"] == "minor units"
    assert listed["edges"] == [["impl", "rev"]]
    assert d1 == {"removed": True}
    assert after["edges"] == []


def test_event_tool_param_is_validated(tmp_path):
    async def go():
        client, _ = await _client(tmp_path)
        try:
            ok = await client.post("/api/v1/unified/sessions/events?tool=codex", json={
                "hook_event_name": "UserPromptSubmit", "session_id": "c1", "cwd": str(tmp_path / "a")})
            bad = await client.post("/api/v1/unified/sessions/events?tool=gpt", json={})
            listed = await (await client.get("/api/v1/unified/sessions")).json()
            return ok.status, bad.status, listed
        finally:
            await client.close()

    ok, bad, listed = _run(go())
    assert (ok, bad) == (200, 400)
    assert next(s for g in listed["groups"] for s in g["sessions"])["tool"] == "codex"
