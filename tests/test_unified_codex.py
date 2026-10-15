"""Spec 004: Codex + Claude events, Codex titles, Codex hooks, autostart plist."""
from __future__ import annotations

import json
import plistlib
import sqlite3
from pathlib import Path

import symphony.unified.sessions as sessions_module
from symphony.unified import codex_titles
from symphony.unified.autostart import LABEL, plist_xml
from symphony.unified.hooks import TARGET_EVENTS, hooks_installed, install_hooks, uninstall_hooks
from symphony.unified.sessions import SessionStore


def _store():
    return SessionStore(lambda: [], watch_root=Path("/w"), ignore_roots=[],
                        repo_info=lambda cwd: (None, None))


def _state(store, sid="s1"):
    return next(s for g in store.snapshot()["groups"] for s in g["sessions"] if s["id"] == sid)


def test_codex_lifecycle_and_permission_request(monkeypatch):
    monkeypatch.setattr(sessions_module, "codex_title", lambda sid: "기도노트 사이트 기획하자")
    store = _store()
    ev = lambda name, **kw: store.apply(
        {"hook_event_name": name, "session_id": "s1", "cwd": "/w/notes", **kw}, tool="codex")
    ev("UserPromptSubmit", prompt="plan it")
    assert (_state(store)["state"], _state(store)["tool"]) == ("working", "codex")
    assert _state(store)["title"] == "기도노트 사이트 기획하자"
    ev("PermissionRequest", tool_name="Bash", tool_input={"description": "npm install"})
    assert _state(store)["state"] == "waiting"
    assert _state(store)["message"] == "승인 요청: npm install"
    ev("PreToolUse", tool_name="Bash")
    assert _state(store)["state"] == "working"
    ev("Interrupt")
    assert _state(store)["state"] == "done"


def test_claude_permission_request_without_description():
    store = _store()
    store.apply({"hook_event_name": "PermissionRequest", "session_id": "s1", "cwd": "/w/a",
                 "tool_name": "Write"})
    assert _state(store)["message"] == "승인 요청: Write"
    assert _state(store)["tool"] == "claude"


def test_codex_title_prefers_name_and_is_read_only(tmp_path, monkeypatch):
    monkeypatch.setattr(codex_titles, "_cache", {})
    db = tmp_path / "state_5.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute("create table threads (id text, name text, title text)")
        conn.execute("insert into threads values ('a', '탭 이름', '첫 메시지')")
        conn.execute("insert into threads values ('b', '', '첫 메시지만')")
    before = db.stat().st_mtime
    assert codex_titles.codex_title("a", tmp_path) == "탭 이름"
    assert codex_titles.codex_title("b", tmp_path) == "첫 메시지만"
    assert codex_titles.codex_title("zz", tmp_path) is None
    assert codex_titles.codex_title("x", tmp_path / "missing") is None
    assert db.stat().st_mtime == before


def test_codex_hooks_use_codex_events_and_tool_param(tmp_path):
    path = tmp_path / "hooks.json"
    orca = {"hooks": [{"type": "command", "command": ": orca-agent-hook-form=1"}]}
    path.write_text(json.dumps({"hooks": {"Stop": [orca]}}))
    assert install_hooks(8787, path, "codex") == list(TARGET_EVENTS["codex"])
    data = json.loads(path.read_text())
    assert data["hooks"]["Stop"][0] == orca
    ours = data["hooks"]["Interrupt"][0]
    assert "matcher" not in ours
    assert "?tool=codex" in ours["hooks"][0]["command"]
    assert hooks_installed(path, "codex") == list(TARGET_EVENTS["codex"])
    uninstall_hooks(path, "codex")
    assert json.loads(path.read_text())["hooks"] == {"Stop": [orca]}


def test_autostart_plist_runs_python_directly():
    xml = plist_xml(python="/venv/bin/python", script="/venv/bin/symphony", port=9000,
                    path_env="/usr/bin:/bin", log=Path("/tmp/x.log"))
    data = plistlib.loads(xml.encode())
    assert data["Label"] == LABEL
    assert data["ProgramArguments"] == ["/venv/bin/python", "/venv/bin/symphony", "unified", "--port", "9000"]
    assert data["KeepAlive"] is True and data["RunAtLoad"] is True
    assert data["EnvironmentVariables"]["PATH"] == "/usr/bin:/bin"


def test_autostart_plist_passes_watch_folder():
    xml = plist_xml(python="/p", script="/s", port=8787, path_env="/bin",
                    extra_args=["--watch", "/Users/x/code"])
    assert plistlib.loads(xml.encode())["ProgramArguments"][-2:] == ["--watch", "/Users/x/code"]
