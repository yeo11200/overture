"""HTTP surface of `symphony unified`: one board across every hosted project.

Board/card shapes reuse the per-project web API serializers so the unified
view and a single-project board never disagree about a ticket.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from aiohttp import web

from ..hub import _HUB_BIND_HOST, _hub_guard
from ..issue import registration_order_key
from ..trackers.file import FileBoardTracker, parse_ticket_file
from ..webapi import (
    _check_description,
    _check_identifier,
    _check_priority,
    _check_state,
    _check_title,
    _columns_payload,
    _issue_card,
    _json_error,
    _live_by_identifier,
    _read_json,
    _valid_states,
    _wrap,
)
from .supervisor import ProjectRuntime, Supervisor

STATIC_DIR = Path(__file__).resolve().parent.parent / "web" / "static"


def _project_json(runtime: ProjectRuntime) -> dict[str, Any]:
    return {
        "id": runtime.project.id,
        "name": runtime.project.name,
        "repo": runtime.project.git_repo,
        "status": runtime.status,
        "error": runtime.error,
        "paused": runtime.status == "paused",
    }


async def _project_cards(runtime: ProjectRuntime) -> list[dict[str, Any]]:
    cfg = runtime.cfg
    if cfg is None or cfg.tracker.kind != "file":
        return []
    tracker = FileBoardTracker(cfg.tracker)
    issues = await asyncio.to_thread(
        tracker.fetch_issues_by_states, list(_valid_states(cfg).values())
    )
    orch = runtime.orchestrator
    live = _live_by_identifier(orch) if orch is not None else {}
    cards = []
    for issue in sorted(issues, key=registration_order_key):
        attention = orch.issue_attention(issue) if orch is not None else None
        card = _issue_card(issue, attention=attention)
        card["project_id"] = runtime.project.id
        card["live"] = live.get(issue.identifier)
        cards.append(card)
    return cards


def _merge_columns(runtimes: list[ProjectRuntime]) -> list[dict[str, Any]]:
    """Union of every project's lanes, in first-seen order."""
    merged: dict[str, dict[str, Any]] = {}
    for runtime in runtimes:
        if runtime.cfg is None:
            continue
        for column in _columns_payload(runtime.cfg):
            merged.setdefault(
                column["name"], {"name": column["name"], "terminal": column["terminal"]}
            )
    return list(merged.values())


def build_unified_app(supervisor: Supervisor, *, discovery: Any) -> web.Application:
    app = web.Application(middlewares=[_hub_guard], client_max_size=256 * 1024)

    def _runtime(request: web.Request) -> ProjectRuntime:
        runtime = supervisor.get(request.match_info["project_id"])
        if runtime is None:
            raise web.HTTPNotFound(
                text='{"error":{"code":"project_not_found","message":"unknown project"}}',
                content_type="application/json",
            )
        return runtime

    def _file_tracker(runtime: ProjectRuntime) -> FileBoardTracker:
        if runtime.cfg is None or runtime.cfg.tracker.kind != "file":
            raise web.HTTPConflict(
                text='{"error":{"code":"board_unavailable","message":"project has no file board"}}',
                content_type="application/json",
            )
        return FileBoardTracker(runtime.cfg.tracker)

    async def index(_request: web.Request) -> web.FileResponse:
        return web.FileResponse(STATIC_DIR / "unified.html")

    async def board(_request: web.Request) -> web.Response:
        runtimes = supervisor.runtimes()
        per_project = await asyncio.gather(
            *(_project_cards(rt) for rt in runtimes), return_exceptions=True
        )
        cards: list[dict[str, Any]] = []
        projects = []
        for runtime, result in zip(runtimes, per_project, strict=True):
            payload = _project_json(runtime)
            if isinstance(result, BaseException):
                payload["board_error"] = str(result)
            else:
                cards.extend(result)
            projects.append(payload)
        return web.json_response(
            {"projects": projects, "columns": _merge_columns(runtimes), "cards": cards},
            headers={"Cache-Control": "no-store"},
        )

    async def pause(request: web.Request) -> web.Response:
        runtime = _runtime(request)
        paused = request.match_info["action"] == "pause"
        supervisor.set_paused(runtime.project.id, paused)
        return web.json_response(_project_json(runtime))

    async def create_issue(request: web.Request) -> web.Response:
        runtime = _runtime(request)
        tracker = _file_tracker(runtime)
        body = await _read_json(request)
        cfg = runtime.cfg
        assert cfg is not None
        state = (
            _check_state(cfg, body["state"])
            if body.get("state")
            else (cfg.tracker.active_states[0] if cfg.tracker.active_states else "Todo")
        )
        identifier, _ = await asyncio.to_thread(
            lambda: tracker.create_validated(
                identifier=None,
                title=_check_title(body.get("title")),
                state=state,
                priority=_check_priority(body.get("priority")),
                description=_check_description(body.get("description")),
            )
        )
        return web.json_response(
            {"project_id": runtime.project.id, "identifier": identifier}, status=201
        )

    async def issue_detail(request: web.Request) -> web.Response:
        runtime = _runtime(request)
        tracker = _file_tracker(runtime)
        identifier = _check_identifier(request.match_info["identifier"])
        path = await asyncio.to_thread(tracker.find_path, identifier)
        if path is None:
            return _json_error(404, "issue_not_found", f"unknown issue {identifier}")
        _front, body_text = await asyncio.to_thread(parse_ticket_file, path)
        issue = await asyncio.to_thread(tracker.fetch_issue_full_by_id, identifier)
        orch = runtime.orchestrator
        card: dict[str, Any] = (
            _issue_card(issue) if issue else {"identifier": identifier}
        )
        card["project_id"] = runtime.project.id
        card["description"] = body_text
        card["live"] = _live_by_identifier(orch).get(identifier) if orch else None
        return web.json_response(card)

    async def discovery_state(_request: web.Request) -> web.Response:
        if discovery is None:
            return web.json_response({"enabled": False, "root": None, "failures": {}})
        return web.json_response(
            {"enabled": True, "root": str(discovery.root), "failures": discovery.failures()}
        )

    async def discovery_retry(request: web.Request) -> web.Response:
        if discovery is None:
            return _json_error(409, "discovery_disabled", "discovery is not enabled")
        body = await _read_json(request)
        path = body.get("path")
        if not isinstance(path, str) or not path:
            return _json_error(400, "invalid_path", "path is required")
        discovery.retry(path)
        added = await discovery.scan_once()
        return web.json_response({"added": added, "failures": discovery.failures()})

    app.router.add_get("/", index)
    app.router.add_static("/static/", STATIC_DIR)
    app.router.add_get("/api/v1/unified/board", _wrap(board))
    app.router.add_post(
        "/api/v1/unified/projects/{project_id}/{action:pause|resume}", _wrap(pause)
    )
    app.router.add_post(
        "/api/v1/unified/projects/{project_id}/issues", _wrap(create_issue)
    )
    app.router.add_get(
        "/api/v1/unified/projects/{project_id}/issues/{identifier}", _wrap(issue_detail)
    )
    app.router.add_get("/api/v1/unified/discovery", _wrap(discovery_state))
    app.router.add_post("/api/v1/unified/discovery/retry", _wrap(discovery_retry))
    return app


async def run_unified_app(
    app: web.Application, host: str, port: int
) -> tuple[web.AppRunner, int]:
    app[_HUB_BIND_HOST] = host
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=host, port=port)
    await site.start()
    server = getattr(site, "_server", None)
    bound = port
    if server is not None and server.sockets:
        bound = int(server.sockets[0].getsockname()[1])
    return runner, bound
