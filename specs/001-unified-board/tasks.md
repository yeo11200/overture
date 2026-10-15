# Tasks: 통합 보드 (Unified Board)

**Input**: spec.md, plan.md (specs/001-unified-board/)

## Phase 1: Foundational (blocks all stories)

- [x] T001 `Orchestrator(isolated_env=True)`: skip `os.environ["SYMPHONY_WORKFLOW_DIR"]` write; add SYMPHONY_WORKFLOW_DIR/SYMPHONY_CLI to `_dispatch_env_for` in isolated mode — src/symphony/orchestrator/core.py
- [x] T002 `Orchestrator.dispatch_paused`: skip dispatch in `_on_tick` after reconcile and re-park in `_on_retry_timer` — src/symphony/orchestrator/core.py
- [x] T003 [P] Tests for T001/T002 — tests/test_unified_orchestrator.py

## Phase 2: US2 — 하나의 프로세스 (P1)

- [x] T004 Supervisor: start/stop one Orchestrator per file-tracker project, per-project error isolation, status (running/paused/error/conflict/missing) — src/symphony/unified/supervisor.py
- [x] T005 Ownership marker `.symphony/run/unified.json`; supervisor refuses projects whose legacy service is running; `symphony service start` refuses projects owned by a live unified process — src/symphony/unified/supervisor.py, src/symphony/service.py
- [x] T006 [P] Tests: error isolation, conflict both directions, pause — tests/test_unified_supervisor.py

## Phase 3: US1 — 한 화면 (P1)

- [x] T007 API: GET board, POST pause/resume, POST issue create, GET issue detail; reuse `_issue_card`, `_columns_payload`, `_live_by_identifier`, `_hub_guard` — src/symphony/unified/api.py
- [x] T008 CLI `symphony unified [--host --port --watch --exclude]` — src/symphony/unified/cli.py, src/symphony/cli/main.py
- [x] T009 UI: unified.html/js/css (project chips w/ filter+pause, kanban, live badges, Human Review emphasis, detail panel, new-ticket dialog, 2s polling) — src/symphony/web/static/
- [x] T010 [P] API tests (aiohttp test client) — tests/test_unified_api.py
- [x] T011 e2e (model-free) against mock backend — tests/unified.e2e.ts

## Phase 4: US3 — 자동 등록 (P2)

- [x] T012 Discovery loop (startup + 5 min): git dir only, skip worktrees/registered/excluded/failed; record failures to unified-failures.json; retry endpoint — src/symphony/unified/discovery.py, api.py
- [x] T013 [P] Tests for discovery filters and failure memo — tests/test_unified_discovery.py

## Phase 5: Polish

- [x] T014 Full test suite green; measure process/port/RSS with 7 projects (SC-002/003); README section
