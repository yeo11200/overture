"""Overture demo server: sample projects only, nothing from this machine.

Everything lives in a temp folder: git repos (one with a worktree), Kanban
tickets driven by the mock agent backend, and fake Claude transcripts that
give the sessions their titles. The process scan / Orca lookup is switched
off, so no real terminal, session or project ever shows up.

    python docs/demo/demo_server.py --port 8799
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(tempfile.mkdtemp(prefix="overture-demo-"))
os.environ["SYMPHONY_PROJECTS_FILE"] = str(ROOT / "state" / "projects.json")

import symphony.unified.sessions as sessions_module  # noqa: E402
from symphony.projects import REGISTRY_VERSION  # noqa: E402
from symphony.trackers.file import FileBoardTracker  # noqa: E402
from symphony.unified.cli import main  # noqa: E402
from symphony.unified.titles import transcript_dir_for  # noqa: E402
from symphony.workflow import WorkflowState  # noqa: E402

TRANSCRIPTS = ROOT / "transcripts"

# Sample sessions: id -> (folder, tool, title). The recorder posts their events.
SESSIONS = {
    "s-checkout": ("shop-web", "claude", "결제 페이지 리디자인"),
    "s-cart": ("shop-web-cart", "claude", "장바구니 수량 버그 수정"),
    "s-units": ("payments-api", "codex", "금액 minor units 변환"),
    "s-review": ("payments-api-review", "claude", "minor units 구현 리뷰"),
    "s-push": ("mobile-app", "claude", "푸시 알림 권한 흐름"),
    "s-docs": ("docs-site", "codex", "API 문서 갱신"),
}

TICKETS = {
    "shop-web": [("Todo", "결제 버튼 접근성 라벨"), ("Human Review", "쿠폰 입력 UX 개선")],
    "payments-api": [("Todo", "환불 웹훅 재시도"), ("Done", "통화 코드 검증")],
    "mobile-app": [("Todo", "딥링크 라우팅 정리")],
}


def git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def make_repo(name: str, branch: str) -> Path:
    repo = ROOT / name
    repo.mkdir(parents=True)
    git("init", "-q", "-b", branch, cwd=repo)
    git("-c", "user.name=demo", "-c", "user.email=demo@example.com",
        "commit", "-q", "--allow-empty", "-m", "init", cwd=repo)
    return repo


def add_worktree(repo: Path, name: str, branch: str) -> None:
    git("worktree", "add", "-q", "-b", branch, str(ROOT / name), cwd=repo)


def write_workflow(repo: Path) -> Path:
    (repo / "kanban").mkdir(exist_ok=True)
    workflow = repo / "WORKFLOW.md"
    workflow.write_text(
        "---\n"
        "tracker: { kind: file, board_root: ./kanban,"
        " active_states: [Todo, \"In Progress\"], terminal_states: [\"Human Review\", Done] }\n"
        "polling: { interval_ms: 3000 }\n"
        f"workspace: {{ root: {ROOT}/workspaces/{repo.name} }}\n"
        "agent: { kind: codex, max_concurrent_agents: 1 }\n"
        f"codex: {{ command: {sys.executable} -m symphony.mock_codex }}\n"
        "---\nDemo ticket {{ issue.identifier }}\n"
    )
    return workflow


def main_demo() -> int:
    shop = make_repo("shop-web", "main")
    add_worktree(shop, "shop-web-cart", "fix/cart-quantity")
    pay = make_repo("payments-api", "main")
    add_worktree(pay, "payments-api-review", "review/minor-units")
    make_repo("mobile-app", "develop")
    make_repo("docs-site", "main")

    projects = []
    for port, name in enumerate(TICKETS, start=12000):
        repo = ROOT / name
        workflow = write_workflow(repo)
        cfg, err = WorkflowState(workflow).reload()
        assert cfg is not None, err
        tracker = FileBoardTracker(cfg.tracker)
        for state, title in TICKETS[name]:
            tracker.create_validated(identifier=None, title=title, state=state)
        projects.append({"id": name, "name": name, "git_repo": str(repo),
                         "workflow": str(workflow), "host": "127.0.0.1", "port": port})
    state = ROOT / "state"
    state.mkdir(exist_ok=True)
    (state / "projects.json").write_text(
        json.dumps({"version": REGISTRY_VERSION, "projects": projects})
    )

    titles = {}
    manifest = {}
    for sid, (folder, tool, title) in SESSIONS.items():
        cwd = str(ROOT / folder)
        titles[sid] = title
        transcript = transcript_dir_for(cwd, TRANSCRIPTS) / f"{sid}.jsonl"
        if tool == "claude":
            transcript.parent.mkdir(parents=True, exist_ok=True)
            transcript.write_text(
                json.dumps({"type": "ai-title", "aiTitle": title, "sessionId": sid}) + "\n"
            )
        manifest[sid] = {"cwd": cwd, "tool": tool, "transcript": str(transcript)}
    (ROOT / "sessions.json").write_text(json.dumps(manifest, ensure_ascii=False))
    print(f"demo root: {ROOT}", file=sys.stderr, flush=True)

    # Sample data only: no process scan / Orca, fake transcripts and Codex titles.
    sessions_module.SessionStore.run_scanner = (  # type: ignore[method-assign]
        lambda self, *a, **k: asyncio.sleep(10**9)
    )
    sessions_module.codex_title = lambda sid: titles.get(sid)
    original_init = sessions_module.SessionStore.__init__

    def init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs["transcripts_root"] = TRANSCRIPTS
        original_init(self, *args, **kwargs)

    sessions_module.SessionStore.__init__ = init  # type: ignore[method-assign]
    return main([*sys.argv[1:], "--watch", ""])


if __name__ == "__main__":
    sys.exit(main_demo())
