# Implementation Plan: 통합 보드 (Unified Board)

**Branch**: `feat/unified-board` | **Date**: 2026-10-15 | **Spec**: [spec.md](spec.md)

## Summary

새 명령 `symphony unified`가 프로세스 1개·포트 1개(기본 8787)로 뜬다. 레지스트리의 모든 파일 트래커 프로젝트에 대해 기존 `Orchestrator`를 같은 이벤트 루프 안의 태스크로 띄우고(프로젝트별 HTTP 서버 없음), 전 프로젝트를 모은 보드 API와 새 통합 칸반 화면을 서빙한다. 같은 프로세스가 감시 폴더를 주기적으로 스캔해 새 저장소를 자동 등록한다. 기존 `symphony service`/프로젝트별 포트 방식은 그대로 둔다.

## Technical Context

**Language/Version**: Python 3.12 (기존), 바닐라 JS/CSS (기존 `web/static`과 동일, 빌드 단계 없음)
**Primary Dependencies**: aiohttp (기존). 새 의존성 없음.
**Storage**: 프로젝트별 기존 `<repo>/.symphony/state.db`, 레지스트리 `projects.json`(기존). 자동 등록 실패 기록은 레지스트리 옆 JSON 파일 1개.
**Testing**: pytest (기존 `tests/`), UI는 `e2e` 스킬로 `tests/*.e2e.ts` (모델 없는 테스트)
**Target Platform**: macOS 로컬, 127.0.0.1
**Performance Goals**: 상태 반영 ≤5초(2초 폴링), 유휴 시 단일 프로세스(목표 <120MB, 7개 프로젝트)
**Constraints**: 업스트림 코드 변경 최소화(포크 유지보수), 기존 테스트 통과 유지

## 조사 결과 (코드 근거)

- 진입 흐름: `cli/main.py:178 _run()` → `WorkflowState.reload()` → `Orchestrator(state).start()` → `build_app()` → `run_server()`. 오케스트레이터는 HTTP 없이도 독립 동작(`_spawn_tick_loop`, `core.py:2986`).
- 보드 데이터: `webapi.handle_board`(1310)의 카드 생성 `_issue_card`(514), 실행 상태 `Orchestrator.snapshot()`(core.py:3109). 티켓 ID는 프로젝트 간 중복 가능 → `(project_id, identifier)`로 식별.
- **한 프로세스에서 N개 돌릴 때 깨지는 지점**:
  1. `core.py:2957` `os.environ["SYMPHONY_WORKFLOW_DIR"]` 전역 변경 → 마지막에 뜬 프로젝트 경로가 다른 프로젝트 에이전트 환경에 샘. 백엔드는 `os.environ.copy()`로 env를 만듦(codex.py:338, per_turn.py:344).
  2. `core.py:933` `SERVICE_INSTANCE_ENV` pop → 첫 오케스트레이터만 인스턴스 ID를 받음.
  3. 중복 실행 방지가 `service.py` 락에만 있음 → 통합 서버와 기존 개별 서비스가 같은 프로젝트를 동시에 돌릴 수 있음.
  4. 프로젝트 단위 일시정지 없음(워커 단위 `pause_worker`만 존재).
  5. 전역 로거에 프로젝트 태그 없음.
- 기존 webapi를 프로젝트별 sub-app으로 마운트하는 안은 `_api_guard`가 `request.path.startswith("/api/")`(webapi.py:368)로 검사해 접두 경로에서 **인증 검사가 꺼지는** 문제가 있어 이번 범위에서 제외.

## 설계

### 1. 오케스트레이터 수정 (최소 변경, `orchestrator/core.py`, `backends/`)
- `Orchestrator`가 인스턴스별 `extra_env`(SYMPHONY_WORKFLOW_DIR 등)를 들고, 백엔드 subprocess env 생성 시 `os.environ` 위에 덮어쓴다. 기존 `os.environ` 쓰기는 단일 모드 호환을 위해 유지하되 통합 모드에서는 건너뜀(`Orchestrator(..., isolated_env=True)`).
- `SERVICE_INSTANCE_ENV`는 통합 모드에서 pop하지 않고 프로젝트별 ID를 생성자 인자로 받는다.
- 프로젝트 일시정지: `Orchestrator.dispatch_paused` 플래그. `_on_tick`에서 새 디스패치만 건너뛰고 실행 중 작업·재조정은 계속.

### 2. 슈퍼바이저 (`src/symphony/unified/supervisor.py`, 신규)
- 레지스트리를 읽어 `kind: file` 프로젝트마다 `Orchestrator`를 시작. 각 프로젝트 시작/틱 예외는 해당 프로젝트 상태를 `error`로 표시하고 다른 프로젝트는 계속(FR-008).
- 시작 전 `service.py`의 락/상태로 기존 개별 서비스가 떠 있으면 그 프로젝트는 `conflict` 상태로 띄우지 않고 화면에 표시(FR-009). 통합 서버 자신도 프로젝트별 락을 잡아 반대 방향도 막음.
- 로그 라인에 `project=<id>` 필드 추가(contextvar).

### 3. 자동 등록 (`src/symphony/unified/discovery.py`, 신규)
- 5분 간격 + 시작 시 1회 `~/Documents/_shin/*` 스캔(설정 가능). 조건: `.git`이 디렉터리(워크트리 제외), 미등록, 제외 목록·실패 기록에 없음.
- 기존 `create_or_adopt_project()` 호출 → 성공 시 슈퍼바이저에 즉시 추가. 실패 시 `unified-failures.json`에 경로·사유·시각 기록 후 재시도 안 함(FR-011). 화면에서 재시도 버튼.
- 서버가 사용자 터미널에서 실행되므로 macOS 문서 폴더 권한 문제(launchd TCC) 없음.

### 4. 통합 API (`src/symphony/unified/api.py`, 신규, 한 aiohttp 앱)
- `GET /api/v1/unified/board` → `{projects:[{id,name,status,paused,columns}], columns:[합집합 순서], cards:[{project_id, ...기존 _issue_card 필드, live:{status,turn_count,last_event,...}}]}`
- `POST /api/v1/unified/projects/{id}/pause|resume`
- `POST /api/v1/unified/projects/{id}/issues` (티켓 생성, 기존 파일 트래커 쓰기 함수 재사용)
- `GET /api/v1/unified/projects/{id}/issues/{identifier}` (본문 + 실행 기록)
- `POST /api/v1/unified/discovery/retry`
- 보안: 기존 hub의 `_hub_guard`(루프백·호스트 검사·교차 출처 차단) 재사용.

### 5. 통합 화면 (`src/symphony/web/static/unified.{html,js,css}`, 신규)
- 기존 `style.css` 토큰 재사용. 상단: 프로젝트 칩(필터 + 일시정지 토글 + 상태 점), 본문: 상태 칸 칸반, 카드에 프로젝트 색 띠·ID·제목·실행 중 표시·턴 수·마지막 이벤트. Human Review 칸 강조 + 개수 배지 + 브라우저 탭 제목에 대기 수.
- 2초 폴링(웹소켓은 필요할 때). 카드 클릭 → 오른쪽 상세 패널.
- 프레임워크 도입 안 함: 기존 정적 자산과 같은 방식, 빌드 없음.

### 6. CLI
- `symphony unified [--port 8787] [--watch ~/Documents/_shin] [--exclude oh-my-symphony,mori-memo]`
- 기존 `symphony hub`는 그대로 둠.

## Constitution Check

constitution.md는 템플릿 상태(원칙 미정) → 위반 검사 대상 없음. 기존 리포 규약(AGENTS.md: doctor 선행, 테스트 유지)을 따름.

## Project Structure

```text
specs/001-unified-board/   spec.md, plan.md, tasks.md
src/symphony/unified/      __init__.py, supervisor.py, discovery.py, api.py, cli.py
src/symphony/orchestrator/core.py      (isolated_env, dispatch_paused)
src/symphony/backends/{codex,per_turn}.py  (extra_env 병합)
src/symphony/cli/                      (unified 서브커맨드 등록)
src/symphony/web/static/unified.{html,js,css}
tests/test_unified_*.py                pytest
tests/unified.e2e.ts, e2e.config.ts    e2e (모델 없음)
```

## 검증 계획

- pytest: env 격리(두 오케스트레이터가 서로 다른 SYMPHONY_WORKFLOW_DIR를 백엔드에 넘김), 일시정지 시 디스패치 없음, 한 프로젝트 예외 시 다른 프로젝트 틱 지속, 개별 서비스 실행 중이면 conflict, 디스커버리 필터/실패 기록.
- mock 백엔드(`symphony.mock_codex`)로 2개 프로젝트 실제 구동 → 통합 화면 카드 갱신 e2e.
- 실측: `ps`로 프로세스 1개·포트 1개·RSS 측정(SC-002/003).
- 기존 테스트 전체 통과.

## Complexity Tracking

| 결정 | 이유 | 버린 대안 |
|---|---|---|
| 한 이벤트 루프에 N 오케스트레이터 | 자원 절약 요구(US2), 실시간 상태를 직접 읽을 수 있음 | 프로젝트별 headless 자식 프로세스: 프로세스 수 그대로, IPC 필요 |
| 프로젝트 상세 고급 기능(Git 리뷰·채팅·미리보기)은 이번 범위 밖 | sub-app 마운트 시 인증 우회 버그 수정 필요 | 지금 sub-app 마운트: 보안 위험 + 프론트 경로 수정 다수 |
| 위험: 한 프로젝트의 블로킹 호출이 전체를 멈춤 | 수용. 기존 코드는 async, 틱 타임아웃 로그로 감시 | — |
