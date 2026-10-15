# Feature Specification: Agent Board 플러그인 (Claude + Codex)

**Feature Branch**: `feat/agent-board-plugin`
**Created**: 2026-10-15
**Status**: Draft
**Input**: "클로드 코덱스 다 되게 해주고 아이콘 찾아서 넣어주고, 깃헙에서 다운받으면 될 수 있게 플러그인 형태로 개발해줘"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Codex 세션도 Claude처럼 상태가 보인다 (Priority: P1)

Codex 세션도 작업 중 / 나를 기다림(승인 요청) / 완료가 차트에 보이고, 카드 제목은 Orca 탭 제목(없으면 Codex 세션 제목)이다.

**Independent Test**: Codex 훅 이벤트(UserPromptSubmit → PermissionRequest → Stop)를 보내면 같은 카드의 상태가 작업 중 → 나를 기다림 → 완료로 바뀐다.

**Acceptance Scenarios**:
1. **Given** Codex 훅 설치·승인됨, **When** Codex에 프롬프트를 보낸다, **Then** 5초 안에 그 Codex 카드가 "작업 중"이 된다.
2. **Given** Codex가 명령 실행 승인을 기다림, **Then** 카드가 "나를 기다림"으로 강조되고 알림이 뜬다.
3. **Given** Claude Code가 권한 요청(PermissionRequest)으로 멈춤, **Then** Claude 카드도 "나를 기다림"이 된다.

### User Story 2 - 카드에 도구 아이콘이 보인다 (Priority: P2)

카드 제목 옆에 Claude 아이콘 또는 OpenAI(Codex) 아이콘이 보여 도구를 바로 구분한다.

**Independent Test**: Claude 카드와 Codex 카드에 각각 다른 아이콘(접근 가능한 이름 "Claude"/"Codex")이 표시된다.

### User Story 3 - GitHub에서 받아 바로 쓴다 (Priority: P1)

다른 사용자가 Claude Code에서 `/plugin marketplace add yeo11200/oh-my-symphony` → `/plugin install agent-board@oh-my-symphony` 하면 Claude 훅이 자동 적용되고, 안내 스킬 하나로 보드 서버 설치·자동 실행·Codex 훅 설치까지 끝낸다.

**Independent Test**: 새 환경에서 플러그인 설치 후 스킬 안내대로 명령을 실행하면 보드가 뜨고, Claude 세션이 보드에 나타난다.

**Acceptance Scenarios**:
1. **Given** 플러그인 설치됨·보드 서버 없음, **When** Claude Code 세션을 시작한다, **Then** 훅이 1초 안에 조용히 실패하고 세션은 정상 동작한다.
2. **Given** 플러그인 설치됨, **When** `/agent-board` 스킬을 실행한다, **Then** (1) `uv tool install git+https://github.com/yeo11200/oh-my-symphony` (2) `symphony unified autostart install` (3) `symphony unified hooks install --codex` 를 안내·실행하고 보드 주소를 열어 준다.
3. **Given** 예전 방식(settings.json 전역 훅)이 이미 설치됨, **When** 플러그인 훅도 켜짐, **Then** 같은 이벤트가 두 번 반영돼도 상태가 깨지지 않는다(멱등). 안내는 예전 훅 제거를 권한다.

### Edge Cases
- Codex 훅은 Codex `/hooks`에서 사용자가 한 번 승인해야 실행된다 → 설치 명령이 이 사실을 출력한다.
- `symphony` 미설치 상태에서 플러그인만 설치: 훅은 무해(서버 없음), 스킬이 설치를 안내.
- macOS 외 OS의 자동 실행은 이번 범위 밖(명령이 지원 안 함을 알림).

## Requirements *(mandatory)*

- **FR-001**: 이벤트 수신 엔드포인트는 도구 구분(`?tool=claude|codex`)을 받고, Codex 이벤트(SessionStart, UserPromptSubmit, PreToolUse, PermissionRequest, Stop, Interrupt, SessionEnd)와 Claude의 PermissionRequest를 상태로 매핑한다.
- **FR-002**: Codex 세션 제목은 Codex 로컬 상태 DB(`~/.codex/state_5.sqlite` threads.title, 읽기 전용)에서 읽고, Orca 탭과 제목으로 짝을 맞춘다.
- **FR-003**: `symphony unified hooks install --codex|--claude` 로 각 도구 훅을 추가만 하고(멱등, 백업), `uninstall`로 표식 항목만 제거한다.
- **FR-004**: 카드에 도구 아이콘(인라인 SVG, simple-icons CC0)과 접근 가능한 이름을 표시한다.
- **FR-005**: 저장소 루트에 Claude Code 마켓플레이스(`oh-my-symphony`), `plugins/agent-board`에 플러그인(훅 + 스킬)을 둔다. 훅은 `${CLAUDE_PLUGIN_ROOT}` 스크립트로 이벤트를 보낸다(1초 제한, 항상 성공 종료).
- **FR-006**: `symphony unified autostart install|uninstall|status` 로 macOS launchd 자동 실행을 설정한다(현재 파이썬·symphony 경로로 plist 생성).
- **FR-007**: 저장소에서 바로 `uv tool install git+https://github.com/yeo11200/oh-my-symphony` 로 `symphony`가 설치되고 보드 정적 파일이 포함된다.
- **FR-008**: 같은 이벤트가 중복 도착해도 상태는 멱등이다.

## Success Criteria *(mandatory)*
- **SC-001**: Claude·Codex 세션 모두 상태 변화가 5초 안에 보인다.
- **SC-002**: 새 사용자가 README의 3단계(마켓플레이스 추가 → 플러그인 설치 → `/agent-board`)로 보드를 띄운다.
- **SC-003**: 보드 서버가 꺼져 있어도 Claude/Codex 응답 지연이 1초를 넘지 않는다.

## Assumptions
- 플러그인 이름 `agent-board`(이름이 `claude-`로 시작하면 거부됨), 마켓플레이스 이름 `oh-my-symphony`.
- 이 머신은 플러그인 훅으로 옮기고 settings.json 전역 훅은 제거한다(중복 방지).
- Codex 아이콘은 별도 마크가 없어 OpenAI 마크(simple-icons 13.21.0)를 쓴다. 상표는 각 소유자에게 있다.
