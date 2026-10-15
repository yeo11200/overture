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
    unknown = lambda key: sum(s["state"] == "unknown" for s in groups[key]["sessions"])
    assert (unknown("app"), unknown("app-api"), unknown("folder:other")) == (2, 1, 2)
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


# -- spec 003: repo grouping, titles, inferred unknowns ------------------------

import json as _json
import os as _os

from symphony.unified.titles import title_from_transcript, transcript_dir_for


def _transcript(root: Path, cwd: str, sid: str, *titles: str, mtime: float | None = None) -> Path:
    folder = transcript_dir_for(cwd, root)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{sid}.jsonl"
    lines = [_json.dumps({"type": "user", "message": "hi"})]
    lines += [_json.dumps({"type": "ai-title", "aiTitle": t, "sessionId": sid}) for t in titles]
    path.write_text("\n".join(lines) + "\n")
    if mtime is not None:
        _os.utime(path, (mtime, mtime))
    return path


def _repo_store(tmp_path, repos):
    projects = [Project("dash", "db-ga-dashboard", "/w/dash", "/w/dash/WORKFLOW.md", "127.0.0.1", 1)]
    store = SessionStore(
        lambda: projects,
        watch_root=ROOT,
        ignore_roots=[],
        repo_info=lambda cwd: repos.get(cwd, (None, None)),
        transcripts_root=tmp_path,
    )
    return store


def test_worktree_groups_under_its_repository_with_branch(tmp_path):
    store = _repo_store(tmp_path, {
        "/w/dash": ("/w/dash", "main"),
        "/w/dash-perf": ("/w/dash", "feat/perf"),
        "/w/lib-wt": ("/w/lib", "exp"),
    })
    store.apply(_ev("UserPromptSubmit", sid="a", cwd="/w/dash"))
    store.apply(_ev("UserPromptSubmit", sid="b", cwd="/w/dash-perf"))
    store.apply(_ev("UserPromptSubmit", sid="c", cwd="/w/lib-wt"))
    groups = _groups(store)
    dash = {s["id"]: s for s in groups["dash"]["sessions"]}
    assert set(dash) == {"a", "b"}
    assert dash["b"]["branch"] == "feat/perf"
    assert dash["b"]["folder"] == "dash-perf"
    assert groups["folder:lib"]["sessions"][0]["branch"] == "exp"


def test_title_comes_from_transcript_tail(tmp_path):
    path = _transcript(tmp_path, "/w/dash", "s1", "첫 제목", "데스크탑 카카오 이미지 해상도 변경")
    assert title_from_transcript(path) == "데스크탑 카카오 이미지 해상도 변경"
    store = _repo_store(tmp_path, {})
    store.apply(_ev("UserPromptSubmit", sid="s1", cwd="/w/dash", transcript_path=str(path)))
    assert _groups(store)["dash"]["sessions"][0]["title"] == "데스크탑 카카오 이미지 해상도 변경"


def test_transcript_outside_root_is_not_read(tmp_path):
    outside = tmp_path / "elsewhere"
    path = _transcript(outside, "/w/dash", "s1", "secret")
    store = _repo_store(tmp_path / "root", {})
    store.apply(_ev("UserPromptSubmit", sid="s1", cwd="/w/dash", transcript_path=str(path)))
    assert _groups(store)["dash"]["sessions"][0]["title"] == ""


def test_unknown_processes_get_names_from_newest_transcripts(tmp_path):
    _transcript(tmp_path, "/w/dash", "old", "오래된 세션", mtime=100)
    _transcript(tmp_path, "/w/dash", "new", "Figma 연동", mtime=300)
    _transcript(tmp_path, "/w/dash", "mid", "Orca 스킬", mtime=200)
    _transcript(tmp_path, "/w/dash", "known", "이미 아는 세션", mtime=400)
    store = _repo_store(tmp_path, {})
    store.apply(_ev("UserPromptSubmit", sid="known", cwd="/w/dash"))
    store.reconcile({"/w/dash": 3}, {"/w/notes": 1})
    groups = _groups(store)
    dash = groups["dash"]
    inferred = [s for s in dash["sessions"] if s["state"] == "unknown"]
    assert [s["title"] for s in inferred] == ["Figma 연동", "Orca 스킬"]
    codex = groups["folder:notes"]["sessions"][0]
    assert codex["tool"] == "codex" and codex["state"] == "unknown"
    assert store.alive_ids() >= {"known", "new", "mid"}


def test_unknown_without_transcripts_still_gets_one_card_each(tmp_path):
    store = _repo_store(tmp_path, {})
    store.reconcile({"/w/dash": 2})
    cards = _groups(store)["dash"]["sessions"]
    assert len(cards) == 2 and all(c["state"] == "unknown" for c in cards)


# -- Orca terminals --------------------------------------------------------------

from symphony.unified.sessions import parse_orca_terminals

ORCA = {"ok": True, "result": {"terminals": [
    {"handle": "term_a", "agentIdentity": "claude", "connected": True, "title": "✳ Figma 데스크탑 앱 MCP 연동",
     "worktreePath": "/w/dash", "branch": "refs/heads/main", "lastOutputAt": 1_000_000},
    {"handle": "term_b", "agentIdentity": "claude", "connected": True, "title": "◐ 데스크탑 카카오 이미지 해상도 변경",
     "worktreePath": "/w/dash-perf", "branch": "refs/heads/feat/perf", "lastOutputAt": 2_000_000},
    {"handle": "term_c", "agentIdentity": "codex", "connected": True, "title": "기도노트 사이트 기획하자 | _shin",
     "worktreePath": "/w/notes", "branch": None, "lastOutputAt": 0},
    {"handle": "term_d", "agentIdentity": None, "connected": True, "title": "Terminal 1", "worktreePath": "/w/dash"},
    {"handle": "term_e", "agentIdentity": "claude", "connected": False, "title": "✳ gone", "worktreePath": "/w/dash"},
]}}


def test_parse_orca_terminals_reads_tab_titles_and_state():
    terms = {t["handle"]: t for t in parse_orca_terminals(ORCA)}
    assert set(terms) == {"term_a", "term_b", "term_c"}
    assert (terms["term_a"]["title"], terms["term_a"]["state"]) == ("Figma 데스크탑 앱 MCP 연동", "idle")
    assert (terms["term_b"]["state"], terms["term_b"]["branch"]) == ("working", "feat/perf")
    assert (terms["term_c"]["title"], terms["term_c"]["tool"]) == ("기도노트 사이트 기획하자", "codex")


def test_orca_is_the_session_list_and_merges_hook_state(tmp_path):
    store = _repo_store(tmp_path, {"/w/dash-perf": ("/w/dash", "feat/perf")})
    path = _transcript(tmp_path, "/w/dash", "s1", "Figma 데스크탑 앱 MCP 연동")
    store.apply(_ev("Notification", sid="s1", cwd="/w/dash", message="needs permission",
                    transcript_path=str(path)))
    store.apply(_ev("UserPromptSubmit", sid="outside", cwd="/w/elsewhere", prompt="not in orca"))
    store.reconcile({"/w/dash": 5, "/w/elsewhere": 1})  # ps unknowns are ignored in Orca mode
    store.set_orca(parse_orca_terminals(ORCA))
    groups = _groups(store)
    dash = {s["id"]: s for s in groups["dash"]["sessions"]}
    assert set(dash) == {"term_a", "term_b"}  # the worktree tab sits under its repo
    assert dash["term_a"]["state"] == "waiting" and dash["term_a"]["message"] == "needs permission"
    assert dash["term_b"]["title"] == "데스크탑 카카오 이미지 해상도 변경"
    assert dash["term_b"]["branch"] == "feat/perf"
    assert groups["folder:notes"]["sessions"][0]["tool"] == "codex"
    assert groups["folder:elsewhere"]["sessions"][0]["id"] == "outside"
    assert store.alive_ids() == {"term_a", "term_b", "term_c", "outside"}


def test_untitled_session_pairs_with_nearest_orca_folder(tmp_path):
    store = _repo_store(tmp_path, {})
    store.apply(_ev("PermissionRequest", sid="h1", cwd="/w/dash/src", tool_name="Bash"))
    store.reconcile({"/w/dash/src": 1})
    store.set_orca([
        {"handle": "parent", "tool": "claude", "title": "상위 폴더 탭", "state": "idle",
         "path": "/w", "branch": None, "last_output": 0},
        {"handle": "near", "tool": "claude", "title": "가까운 탭", "state": "idle",
         "path": "/w/dash", "branch": None, "last_output": 0},
    ])
    cards = {s["id"]: s for g in store.snapshot()["groups"] for s in g["sessions"]}
    assert cards["near"]["state"] == "waiting"
    assert cards["parent"]["state"] == "idle"
