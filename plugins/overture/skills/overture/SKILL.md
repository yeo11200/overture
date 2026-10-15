---
name: overture
description: Set up and open Overture, the local live chart of every Claude Code and Codex session (working / waiting for you / done), grouped by project. Use when the user asks to install, start, open, or fix Overture or the agent board, connect Codex to it, or run it at login.
---

# Overture

Overture is a local board (http://127.0.0.1:8787/) that shows each Claude Code and Codex session as a
card, named after its terminal tab (Orca) or session title, linked to its project, with roles,
threads and dependency arrows. This plugin already sends Claude Code events to it. Run the steps
below yourself; ask the user only where noted.

## 1. Install the board (once)

```bash
command -v overture || uv tool install --python 3.12 git+https://github.com/yeo11200/overture
```

No `uv`? Install it first (`brew install uv`, or `curl -LsSf https://astral.sh/uv/install.sh | sh`).
Update later with `uv tool upgrade overture`.

## 2. Keep it running

macOS (starts at login, restarts if it dies):

```bash
overture autostart install
```

Ask the user whether a folder should auto-register its new git repos as Kanban projects
(for example `~/code`); if yes, add `--watch <folder>`. Other OSes: run `overture` in a terminal or
the user's own service manager.

## 3. Connect Codex (if the user uses Codex)

```bash
overture hooks install --codex
```

Then tell the user: Codex runs new hooks only after approval — open Codex and run `/hooks` once.

## 4. Avoid duplicate Claude events

If an older global install exists (`overture hooks status --claude` lists events), remove it — this
plugin covers Claude Code now:

```bash
overture hooks uninstall --claude
```

## 5. Open it

```bash
open http://127.0.0.1:8787/ 2>/dev/null || xdg-open http://127.0.0.1:8787/
```

Tell the user: click **알림 켜기** once for desktop alerts when a session waits for them; a card's
role badge and "+ 작업 줄기" group agents; drag a card's right dot onto another card to draw a
dependency arrow.

## Troubleshooting

- Board unreachable: `overture autostart status`, then the log it prints.
- Sessions missing titles: titles come from Orca tabs, Claude transcripts (`~/.claude/projects`),
  or Codex's `~/.codex/state_*.sqlite`; a brand-new session gets one after its first reply.
- Different port: set `AGENT_BOARD_PORT` for the hook and pass `--port` to `autostart install`.
