"""Session-monitor hook installer: additive, idempotent, reversible."""
from __future__ import annotations

import json

from symphony.unified.hooks import (
    EVENTS,
    MARKER,
    hooks_installed,
    install_hooks,
    uninstall_hooks,
)

USER_HOOK = {"matcher": "", "hooks": [{"type": "command", "command": "echo mine"}]}


def test_install_is_additive_and_idempotent(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"model": "x", "hooks": {"Stop": [USER_HOOK]}}))

    assert install_hooks(8787, path) == list(EVENTS)
    assert install_hooks(8787, path) == []
    data = json.loads(path.read_text())
    assert data["model"] == "x"
    assert data["hooks"]["Stop"][0] == USER_HOOK
    assert len(data["hooks"]["Stop"]) == 2
    assert MARKER in data["hooks"]["Notification"][0]["hooks"][0]["command"]
    assert hooks_installed(path) == list(EVENTS)
    assert (tmp_path / "settings.json.bak-symphony").exists()


def test_uninstall_removes_only_ours(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"hooks": {"Stop": [USER_HOOK]}}))
    install_hooks(8787, path)

    assert uninstall_hooks(path) == list(EVENTS)
    data = json.loads(path.read_text())
    assert data["hooks"] == {"Stop": [USER_HOOK]}
    assert hooks_installed(path) == []
    assert uninstall_hooks(path) == []


def test_install_creates_missing_settings(tmp_path):
    path = tmp_path / "nested" / "settings.json"
    install_hooks(9000, path)
    command = json.loads(path.read_text())["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    assert "127.0.0.1:9000/api/v1/unified/sessions/events" in command
    assert "-m 1" in command and "|| true" in command
