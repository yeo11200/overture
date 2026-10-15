"""Install the Claude Code hooks that feed the unified session monitor.

Entries are appended to ~/.claude/settings.json and tagged with MARKER so
install is idempotent and uninstall removes only what it added. The command
gives up after one second and always exits 0, so a stopped unified server
never slows down or fails a Claude Code session.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

MARKER = "# symphony-session-monitor"
EVENTS = ("SessionStart", "UserPromptSubmit", "Notification", "Stop", "SessionEnd")
DEFAULT_SETTINGS = Path.home() / ".claude" / "settings.json"


def hook_command(port: int) -> str:
    return (
        "curl -s -m 1 -o /dev/null -X POST -H 'Content-Type: application/json' "
        f"--data-binary @- http://127.0.0.1:{port}/api/v1/unified/sessions/events "
        f"|| true {MARKER}"
    )


def _load(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object")
    return data


def _save(path: Path, data: dict[str, Any]) -> None:
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + ".bak-symphony"))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp-symphony")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def _ours(group: Any) -> bool:
    return isinstance(group, dict) and any(
        MARKER in str(h.get("command", "")) for h in group.get("hooks", []) if isinstance(h, dict)
    )


def hooks_installed(path: Path = DEFAULT_SETTINGS) -> list[str]:
    hooks = _load(path).get("hooks", {})
    return [e for e in EVENTS if any(_ours(g) for g in hooks.get(e, []))]


def install_hooks(port: int = 8787, path: Path = DEFAULT_SETTINGS) -> list[str]:
    """Add missing monitor hooks; returns the events that were added."""
    data = _load(path)
    hooks = data.setdefault("hooks", {})
    added = []
    for event in EVENTS:
        groups = hooks.setdefault(event, [])
        if any(_ours(g) for g in groups):
            continue
        groups.append(
            {"matcher": "", "hooks": [{"type": "command", "command": hook_command(port)}]}
        )
        added.append(event)
    if added:
        _save(path, data)
    return added


def uninstall_hooks(path: Path = DEFAULT_SETTINGS) -> list[str]:
    """Remove only the monitor hooks; returns the events touched."""
    data = _load(path)
    hooks = data.get("hooks", {})
    removed = []
    for event in EVENTS:
        groups = hooks.get(event, [])
        kept = [g for g in groups if not _ours(g)]
        if len(kept) != len(groups):
            removed.append(event)
            if kept:
                hooks[event] = kept
            else:
                hooks.pop(event)
    if removed:
        _save(path, data)
    return removed
