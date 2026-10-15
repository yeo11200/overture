# Implementation Plan: 세션 감시 (Session Monitor)

**Branch**: `feat/session-monitor` | **Date**: 2026-10-15 | **Spec**: [spec.md](spec.md)

## Summary

Claude Code 전역 훅이 상태 이벤트를 `symphony unified`(8787)로 POST하고, 서버는 세션 상태를 메모리에 유지한다. 15초마다 `ps`+`lsof`로 실행 중인 claude/codex 프로세스의 작업 폴더를 세어 이벤트가 없는 세션을 "상태 모름"으로 채우고, 프로세스가 사라진 폴더의 세션을 정리한다. 통합 화면 상단에 프로젝트별 세션 줄을 추가한다.

## Technical Context

- Python 3.12 / aiohttp (기존), 바닐라 JS. 새 의존성 없음.
- 저장소: 없음(메모리만, FR-008).
- 테스트: pytest(이벤트→상태 전이, 프로젝트 매핑, 프로세스 집계, 정리, 훅 설치/제거 멱등), e2e(이벤트 POST → 화면 반영, 대기 강조).

## 설계

### 1. 훅 (`symphony unified hooks install|uninstall|status`)
- `~/.claude/settings.json`의 `hooks`에 이벤트별 항목을 **추가**: SessionStart, UserPromptSubmit, Stop, Notification, SessionEnd.
- 명령: `curl -s -m 1 -o /dev/null -X POST -H 'Content-Type: application/json' --data-binary @- http://127.0.0.1:8787/api/v1/unified/sessions/events || true` — 서버 없으면 즉시 실패, 최대 1초(FR-006/SC-003).
- 식별: 명령 문자열에 `# symphony-session-monitor` 표식. install은 표식이 있으면 건너뜀(멱등), uninstall은 표식 있는 항목만 제거(FR-007). 수정 전 `settings.json.bak-symphony` 백업.

### 2. 세션 저장소 (`src/symphony/unified/sessions.py`)
- `SessionStore.apply(event)`: `hook_event_name` →
  - SessionStart → idle(완료와 동일 표시 "대기 중"), UserPromptSubmit → working(prompt 앞 120자), Notification → waiting(message), Stop → done, SessionEnd → 삭제.
- 무시: `cwd`가 `~/symphony_workspaces` 아래(Symphony 워커), 서브에이전트 이벤트(SubagentStop 등은 구독 안 함).
- 프로젝트 매핑: 등록 프로젝트 `git_repo` 중 cwd를 포함하는 가장 긴 경로 → project_id, 없으면 `folder:<basename>`.
- `reconcile(process_counts)`: 폴더별 프로세스 수 vs 해당 폴더의 살아있는 세션 수 → 부족분은 `unknown` 개수, 프로세스 0개 폴더의 세션은 제거. done 후 30분 지난 세션 제거(FR-009).

### 3. 프로세스 감지 (`sessions.scan_processes()`)
- `ps -axo pid=,comm=`에서 basename이 `claude` 또는 `codex`인 pid → `lsof -a -d cwd -Fn -p <pids>` 한 번 호출로 cwd 수집. `/`·워커 폴더 제외. 15초 주기 asyncio 태스크(to_thread).

### 4. API
- `POST /api/v1/unified/sessions/events` (hub guard 적용, JSON만, 본문 16KB 제한)
- `GET /api/v1/unified/sessions` → `{groups:[{key, name, project_id|null, sessions:[{id, tool, state, prompt, message, cwd, updated_at}], unknown:N}], counts:{working, waiting, done, unknown}}`

### 5. UI
- 칩 줄 아래 "세션" 줄: 그룹 카드(프로젝트 색) 안에 세션 알약(상태 점·라벨·프롬프트 앞부분·경과 시간), 상태 모름 N개.
- waiting: 보라 강조 + 맨 앞 정렬, 탭 제목 `(대기 N)`, `Notification` API(첫 방문 시 권한 요청 버튼, 같은 세션의 같은 대기에는 1회).
- 요약 줄에 "세션 작업 중 N · 기다림 N".

## Constitution Check
템플릿 상태 → 해당 없음.

## 위험
- Claude Code 훅 페이로드 필드 변경 → 누락 필드는 무시하고 기본값 사용.
- 전역 훅이 모든 세션에 붙음 → curl 1초 제한 + `|| true`로 실패 무해화, uninstall 제공.
