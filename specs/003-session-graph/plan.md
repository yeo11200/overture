# Implementation Plan: 세션 연결 그래프

**Branch**: `feat/session-graph` | **Spec**: [spec.md](spec.md)

## Summary
세션 묶음 기준을 git 공통 저장소로 바꾸고 브랜치를 붙인다. 역할·작업 줄기·화살표 주석 API와 JSON 저장을 추가한다. 프런트에 "차트" 보기(HTML 카드 절대 배치 + SVG 베지어 곡선, 드래그로 화살표)를 추가하고 기본 보기로 한다.

## 설계

### 1. 백엔드 (`unified/sessions.py`, `unified/graph.py` 신규, `api.py`)
- `repo_info(cwd)`: `git -C cwd rev-parse --path-format=absolute --git-common-dir --abbrev-ref HEAD` → (repo_root, branch). 결과는 cwd별 60초 캐시(스캔·이벤트마다 git 호출 방지). 비-git이면 (None, None).
- 그룹 키: 등록 프로젝트 매칭은 **repo_root 기준**으로 먼저(워크트리 → 원래 프로젝트), 실패 시 기존 폴더 규칙.
- 세션 JSON에 `branch`, `folder`(cwd의 감시 루트 바로 아래 이름) 추가. 상태 모름 묶음도 같은 키 규칙.
- `GraphNotes`(graph.py): `{"sessions": {id: {"role", "thread"}}, "edges": [[from, to]]}`를 `~/.symphony/unified-graph.json`에 원자적 저장. 순환 검사(DFS). 살아 있지 않은 세션 ID의 주석·화살표는 스냅샷 때 정리.
- API:
  - `GET /api/v1/unified/sessions` 응답에 각 세션 `role`, `thread` 및 최상위 `edges` 포함.
  - `PATCH /api/v1/unified/sessions/{id}` `{role?, thread?}` (role 허용값 검사, thread ≤40자)
  - `POST /api/v1/unified/sessions/edges` `{from, to}` (자기 자신·순환·없는 세션 409/400), `DELETE /api/v1/unified/sessions/edges` `{from, to}`

### 2. 프런트 (`unified.html/js/css`)
- 상단 보기 전환(차트/칸반, localStorage). 차트에서는 기존 세션 줄 숨김, 칸반에서는 기존 화면 그대로.
- 레이아웃(JS 계산): 그룹마다 세로 블록. 열 x: 프로젝트 40, 작업 줄기 300, 카드 560(너비 280). 카드 높이 72, 간격 16. 작업 줄기 노드는 소속 카드들의 세로 중앙.
- 선: 프로젝트→줄기→카드(또는 프로젝트→카드) 수평 베지어(회색). 의존 화살표: 카드 오른쪽 점끼리 바깥쪽으로 휘는 곡선 + 화살촉(보라), 클릭 영역 넓은 투명 path.
- 카드: 상태 점, 폴더명, `도구 · 브랜치`, 프롬프트/대기 메시지 한 줄, 경과 시간, 역할 배지(`<select>`), 작업 줄기 입력(카드 클릭 시 인라인). waiting 카드는 보라 테두리.
- 드래그: 점에서 pointerdown → 임시 곡선 → 다른 카드 위 pointerup → POST. 조작 중엔 폴링 렌더를 보류(FR-008).
- 폰 폭(<720px): 절대 배치 대신 프로젝트별 세로 목록, 화살표 생략.

### 3. 테스트
- pytest: repo_info 그룹핑(워크트리→원 프로젝트), GraphNotes 저장·순환 거부·정리, API PATCH/edges.
- e2e: 세션 이벤트 2개 → 차트에 프로젝트·카드 보임, 역할 변경 유지, 줄기 지정 시 가운데 노드, API로 화살표 생성 → path 존재 → 클릭 삭제, 칸반 전환.

## 위험
- git 호출 비용: 60초 캐시 + to_thread.
- 폴링 렌더가 드래그를 끊음: 조작 중 렌더 보류 플래그.
