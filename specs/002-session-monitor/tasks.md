# Tasks: 세션 감시

- [x] T001 SessionStore: 이벤트→상태, 프로젝트 매핑, 워커 제외, reconcile/정리 — src/symphony/unified/sessions.py
- [x] T002 [P] tests/test_unified_sessions.py (T001)
- [x] T003 프로세스 감지 scan_processes + 15초 루프 — sessions.py, cli.py
- [x] T004 API: POST events, GET sessions — api.py (+ tests/test_unified_api.py)
- [x] T005 훅 install/uninstall/status (멱등, 백업, 표식) — src/symphony/unified/hooks.py, cli.py (+ tests)
- [x] T006 UI 세션 줄, 대기 강조·알림·탭 제목 — static/unified.{html,js,css}
- [x] T007 e2e: 이벤트 POST → 세션 표시/대기 강조 — tests/unified.e2e.ts
- [x] T008 실제 적용: 훅 설치, 서버 재시작, 실세션으로 확인, 전체 테스트
