"""Session monitor: Claude Code hook events + process scan → per-project sessions."""
from __future__ import annotations

from pathlib import Path

from symphony.projects import Project
from symphony.unified.sessions import SessionStore, parse_lsof_cwds

ROOT = Path("/w")


def _store(clock=None):
    projects = [
        Project("app", "app", "/w/app", "/w/app/WORKFLOW.md", "127.0.0.1", 10000),
        Project("app-api", "app-api", "/w/app/api", "/w/app/api/WORKFLOW.md", "127.0.0.1", 10001),
    ]
    t = clock or [1000.0]
    store = SessionStore(
        lambda: projects,
        watch_root=ROOT,
        ignore_roots=[Path("/home/u/symphony_workspaces")],
        now=lambda: t[0],
    )
    return store, t


def _ev(name, sid="s1", cwd="/w/app", **extra):
    return {"hook_event_name": name, "session_id": sid, "cwd": cwd, **extra}


def _groups(store):
    return {g["key"]: g for g in store.snapshot()["groups"]}


def test_lifecycle_working_waiting_done_end():
    store, _ = _store()
    store.apply(_ev("SessionStart"))
    store.apply(_ev("UserPromptSubmit", prompt="x" * 300))
    s = _groups(store)["app"]["sessions"][0]
    assert s["state"] == "working"
    assert len(s["prompt"]) == 120

    store.apply(_ev("Notification", message="Claude needs your permission to use Bash"))
    s = _groups(store)["app"]["sessions"][0]
    assert s["state"] == "waiting"
    assert "permission" in s["message"]
    assert store.snapshot()["counts"]["waiting"] == 1

    store.apply(_ev("UserPromptSubmit", prompt="go on"))
    assert _groups(store)["app"]["sessions"][0]["state"] == "working"
    assert _groups(store)["app"]["sessions"][0]["message"] == ""

    store.apply(_ev("Stop"))
    assert _groups(store)["app"]["sessions"][0]["state"] == "done"

    store.apply(_ev("SessionEnd"))
    assert "app" not in _groups(store)


def test_cwd_maps_to_deepest_project_or_folder():
    store, _ = _store()
    store.apply(_ev("UserPromptSubmit", sid="a", cwd="/w/app/src/components"))
    store.apply(_ev("UserPromptSubmit", sid="b", cwd="/w/app/api"))
    store.apply(_ev("UserPromptSubmit", sid="c", cwd="/w/db-insurance/web"))
    store.apply(_ev("UserPromptSubmit", sid="d", cwd="/w"))
    groups = _groups(store)
    assert [s["id"] for s in groups["app"]["sessions"]] == ["a"]
    assert [s["id"] for s in groups["app-api"]["sessions"]] == ["b"]
    assert groups["folder:db-insurance"]["name"] == "db-insurance"
    assert groups["folder:db-insurance"]["project_id"] is None
    assert groups["folder:w"]["name"] == "w"


def test_symphony_workers_and_bad_events_are_ignored():
    store, _ = _store()
    store.apply(_ev("UserPromptSubmit", cwd="/home/u/symphony_workspaces/app/TASK-1"))
    store.apply({"hook_event_name": "UserPromptSubmit"})  # no session id
    store.apply(_ev("SubagentStop"))
    assert store.snapshot()["groups"] == []


def test_reconcile_counts_unknown_and_drops_vanished():
    store, _ = _store()
    store.apply(_ev("UserPromptSubmit", sid="a", cwd="/w/app"))
    store.reconcile({"/w/app": 3, "/w/app/api": 1, "/w/other": 2})
    groups = _groups(store)
    assert groups["app"]["unknown"] == 2
    assert groups["app-api"]["unknown"] == 1
    assert groups["folder:other"]["unknown"] == 2
    assert store.snapshot()["counts"]["unknown"] == 5

    store.reconcile({})  # every process gone
    assert store.snapshot()["groups"] == []


def test_reconcile_drops_oldest_sessions_beyond_process_count():
    store, t = _store()
    store.apply(_ev("Stop", sid="old"))
    t[0] += 10
    store.apply(_ev("UserPromptSubmit", sid="new"))
    store.reconcile({"/w/app": 1})
    assert [s["id"] for s in _groups(store)["app"]["sessions"]] == ["new"]


def test_waiting_groups_and_sessions_sort_first():
    store, t = _store()
    store.apply(_ev("UserPromptSubmit", sid="w1", cwd="/w/app"))
    t[0] += 1
    store.apply(_ev("Stop", sid="d1", cwd="/w/app"))
    t[0] += 1
    store.apply(_ev("Notification", sid="n1", cwd="/w/zeta", message="?"))
    groups = store.snapshot()["groups"]
    assert groups[0]["key"] == "folder:zeta"
    assert [s["id"] for s in groups[1]["sessions"]] == ["w1", "d1"]


def test_parse_lsof_cwds():
    out = "p101\nfcwd\nn/w/app\np102\nfcwd\nn/\np103\nfcwd\nn/w/app\n"
    assert parse_lsof_cwds(out) == {"/w/app": 2, "/": 1}
