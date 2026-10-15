# Implementation Plan: Agent Board 플러그인

## 백엔드
- `sessions.apply(event, tool=...)`: 매핑 확장 — claude/codex 공통: SessionStart→idle, UserPromptSubmit/PreToolUse→working, Notification/PermissionRequest→waiting, Stop/Interrupt→done, SessionEnd→삭제. `PermissionRequest`의 `tool_input.description`·`tool_name`을 대기 메시지로. PreToolUse는 waiting 해제용(승인 후 진행).
- Codex 제목: `codex_titles.py` — `sqlite3` 읽기 전용(`file:...?mode=ro` URI)으로 `threads(id,title)` 조회, 30초 캐시. 이벤트 처리 시 `session.title` 채움.
- API: `POST /api/v1/unified/sessions/events?tool=codex`.
- hooks.py: `install_hooks(target="claude"|"codex")`. Codex: `~/.codex/hooks.json`에 같은 형식으로 추가(이벤트 집합 다름), 설치 후 "/hooks에서 승인" 안내 출력.
- `unified/autostart.py`: plist 생성(sys.executable + `symphony` 경로, PATH에 현재 PATH 포함), `launchctl bootstrap/bootout`. status는 `launchctl print`.

## 플러그인
```
.claude-plugin/marketplace.json            {"name":"oh-my-symphony","owner":{"name":"yeo11200"},"plugins":[{"name":"agent-board","source":"./plugins/agent-board",...}]}
plugins/agent-board/.claude-plugin/plugin.json
plugins/agent-board/hooks/hooks.json       SessionStart/UserPromptSubmit/Notification/PermissionRequest/Stop/SessionEnd → scripts/emit.sh claude
plugins/agent-board/scripts/emit.sh        curl -m 1 ... ?tool=$1 || true (포트는 AGENT_BOARD_PORT, 기본 8787)
plugins/agent-board/skills/agent-board/SKILL.md  설치·자동실행·Codex 훅·열기 절차 (Claude가 실행)
```
- 이 머신: settings.json 전역 훅 제거(`hooks uninstall --claude`) → 플러그인 설치.

## 프런트
- `unified-graph.js`: 인라인 SVG 아이콘(claude #D97757, openai currentColor) `role="img" aria-label`.

## 테스트
- pytest: codex/claude 이벤트 매핑·PermissionRequest 메시지·tool 파라미터, codex 제목(임시 sqlite), hooks codex 설치/제거, autostart plist 내용(실행 없이 생성 함수만), 플러그인 JSON 유효성(마켓플레이스·plugin·hooks 스키마 필수 키).
- e2e: codex 이벤트 → 카드 상태·아이콘.
- 실환경: 플러그인 로컬 설치(`/plugin marketplace add` 대신 `claude plugin` CLI 가능하면) 또는 경로 검증, Codex 훅 설치 후 승인 안내.
