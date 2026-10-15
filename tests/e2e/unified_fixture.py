"""Serve `symphony unified` over two throwaway projects for the e2e suite.

Both projects start paused so no worker is ever dispatched; the board, the
filter chips and ticket creation are what the browser test exercises.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

root = Path(tempfile.mkdtemp(prefix="unified-e2e-"))
os.environ["SYMPHONY_PROJECTS_FILE"] = str(root / "projects.json")

from symphony.projects import REGISTRY_VERSION  # noqa: E402
from symphony.trackers.file import FileBoardTracker  # noqa: E402
from symphony.unified.cli import main  # noqa: E402
from symphony.workflow import WorkflowState  # noqa: E402

projects = []
for port, (name, titles) in enumerate(
    [("alpha-app", ["로그인 버그 수정"]), ("beta-api", ["차트 추가", "캐시 튜닝"])],
    start=11000,
):
    repo = root / name
    (repo / "kanban").mkdir(parents=True)
    workflow = repo / "WORKFLOW.md"
    workflow.write_text(
        "---\n"
        "tracker: { kind: file, board_root: ./kanban, active_states: [Todo, \"In Progress\"],"
        " terminal_states: [\"Human Review\", Done] }\n"
        f"workspace: {{ root: {repo}/ws }}\n"
        "agent: { kind: codex }\n"
        "codex: { command: python -m symphony.mock_codex }\n"
        "---\nhi\n"
    )
    cfg, err = WorkflowState(workflow).reload()
    assert cfg is not None, err
    tracker = FileBoardTracker(cfg.tracker)
    for title in titles:
        tracker.create_validated(identifier=None, title=title, state="Todo")
    projects.append(
        {"id": name, "name": name, "git_repo": str(repo), "workflow": str(workflow),
         "host": "127.0.0.1", "port": port}
    )

(root / "projects.json").write_text(
    json.dumps({"version": REGISTRY_VERSION, "projects": projects})
)
(root / "unified-state.json").write_text(json.dumps({"paused": [p["id"] for p in projects]}))

sys.exit(main([*sys.argv[1:], "--watch", ""]))
