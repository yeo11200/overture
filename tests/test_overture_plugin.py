"""The Claude Code plugin / marketplace shipped in this repo is well formed."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from symphony.unified.hooks import TARGET_EVENTS

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "overture"


def test_marketplace_points_at_the_plugin():
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    assert market["name"] and market["owner"]["name"]
    entry = market["plugins"][0]
    assert entry["name"] == "overture"
    assert not entry["name"].startswith("claude-")
    assert (ROOT / entry["source"]).resolve() == PLUGIN
    manifest = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())
    assert manifest["name"] == entry["name"]
    assert manifest["version"] == entry["version"]


def test_hooks_cover_claude_events_and_use_plugin_root():
    hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())["hooks"]
    assert set(hooks) == set(TARGET_EVENTS["claude"])
    for groups in hooks.values():
        handler = groups[0]["hooks"][0]
        assert handler["type"] == "command"
        assert '"${CLAUDE_PLUGIN_ROOT}/scripts/emit.sh" claude' in handler["command"]
        assert handler["timeout"] <= 5


def test_emit_script_is_valid_and_never_fails():
    script = PLUGIN / "scripts" / "emit.sh"
    assert subprocess.run(["sh", "-n", str(script)]).returncode == 0
    # nothing listens on this port: must still exit 0 quickly
    done = subprocess.run(["sh", str(script), "claude"], input=b"{}", timeout=5,
                          env={"PATH": "/usr/bin:/bin", "AGENT_BOARD_PORT": "1"})
    assert done.returncode == 0


def test_skill_has_frontmatter():
    text = (PLUGIN / "skills" / "overture" / "SKILL.md").read_text()
    front = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert front and "name: overture" in front.group(1) and "description:" in front.group(1)
