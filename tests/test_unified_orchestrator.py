"""Unified mode: per-orchestrator env isolation and project-level dispatch pause."""
from __future__ import annotations

import asyncio
from pathlib import Path

from symphony.orchestrator import Orchestrator
from symphony.orchestrator.entries import RetryEntry
from symphony.workflow import WorkflowState
from tests.test_orchestrator_dispatch import _issue, _make_config


class _Handle:
    def cancel(self) -> None:
        pass


def _isolated(workflow: str):
    cfg = _make_config(workflow_path=Path(workflow))
    return Orchestrator(WorkflowState(Path(workflow)), isolated_env=True), cfg


def test_isolated_dispatch_env_carries_own_workflow_dir():
    a, cfg_a = _isolated("/tmp/proj-a/WORKFLOW.md")
    b, cfg_b = _isolated("/tmp/proj-b/WORKFLOW.md")
    issue = _issue("MT-1", state="Todo")

    env_a = a._dispatch_env_for(issue=issue, cfg=cfg_a, is_rewind=False)
    env_b = b._dispatch_env_for(issue=issue, cfg=cfg_b, is_rewind=False)

    assert env_a["SYMPHONY_WORKFLOW_DIR"] == "/tmp/proj-a"
    assert env_b["SYMPHONY_WORKFLOW_DIR"] == "/tmp/proj-b"
    assert env_a["SYMPHONY_CLI"]


def test_default_dispatch_env_unchanged():
    cfg = _make_config()
    orch = Orchestrator(WorkflowState(Path("/tmp/no.md")))
    env = orch._dispatch_env_for(issue=_issue("MT-1"), cfg=cfg, is_rewind=False)
    assert set(env) == {"SYMPHONY_TOKEN_EMA", "SYMPHONY_TOKEN_BUDGET"}


class _StubState:
    def __init__(self, cfg):
        self._cfg = cfg

    def reload(self):
        return self._cfg, None

    def current(self):
        return self._cfg


def _tick_orch(monkeypatch):
    cfg = _make_config()
    orch = Orchestrator(_StubState(cfg))  # type: ignore[arg-type]
    calls: list[str] = []

    async def _noop(*_a, **_k):
        return None

    async def _fetch(_cfg):
        calls.append("fetch")
        return []

    monkeypatch.setattr(orch, "_ensure_run_registry_async", _noop)
    monkeypatch.setattr(orch, "_reconcile_running", _noop)
    monkeypatch.setattr(orch, "_auto_normalize_legacy_human_review_done", _noop)
    monkeypatch.setattr(orch, "_auto_reopen_sources_from_resolved_rcas", _noop)
    monkeypatch.setattr(orch, "_fetch_candidates", _fetch)
    return orch, calls


def test_paused_tick_skips_candidate_fetch(monkeypatch):
    orch, calls = _tick_orch(monkeypatch)
    orch.dispatch_paused = True
    asyncio.run(orch._on_tick())
    assert calls == []


def test_unpaused_tick_fetches_candidates(monkeypatch):
    orch, calls = _tick_orch(monkeypatch)
    try:
        asyncio.run(orch._on_tick())
    except Exception:
        pass  # later tick stages need more wiring; only the fetch matters here
    assert calls == ["fetch"]


def test_paused_retry_timer_reparks(monkeypatch):
    orch, _ = _tick_orch(monkeypatch)
    orch.dispatch_paused = True
    entry = RetryEntry(
        issue_id="MT-1",
        identifier="MT-1",
        attempt=1,
        due_at_ms=0.0,
        timer_handle=_Handle(),  # type: ignore[arg-type]
    )
    orch._dispatch_state.schedule_retry("MT-1", entry)
    reparked: list[str] = []
    monkeypatch.setattr(
        orch, "_repark_paused_retry", lambda r: reparked.append(r.issue_id)
    )

    async def _boom(*_a, **_k):
        raise AssertionError("paused project must not process retries")

    monkeypatch.setattr(orch, "_process_retry", _boom)
    asyncio.run(orch._on_retry_timer("MT-1"))
    assert reparked == ["MT-1"]
