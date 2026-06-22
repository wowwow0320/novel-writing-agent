# Agent Pipeline To-Do

요청하신 4단계 로드맵을 실제 코드 기준으로 추적할 수 있게 정리한 체크리스트입니다.

## Phase 1: 파운데이션 및 배경 설정

- [x] 데이터 스키마 정의
  - 구현: `WORLD_SCHEMA` (`backend/app/services/story_pipeline.py`)
  - 범위: 인물(성격/외형/목표), 배경(장소/시대/분위기), 사건(원인/결과/위험)
- [x] 배경 추출 프롬프트 개발
  - 구현: `foundation_extract_system()` + `/api/agent/foundation/analyze`
- [x] Question 에이전트 로직 구축
  - 구현: `question_classifier_system()` + `classify_required_elements()`

## Phase 2: 생성 및 의사결정 엔진

- [x] Decision 에이전트 알고리즘 설계 (임계값 기반)
  - 구현: `/api/agent/decision`
  - 기준: 글자수/문장수/복잡도
- [ ] Create 에이전트 페르소나 최적화 (장르/문체별)
  - 기존 `genre_writer_role()` 확장 필요 (문체 축 추가)
- [ ] 분할 생성 오케스트레이션
  - `multi_step` 선택 시 블록 순차 생성 및 stitching 로직 추가 필요

## Phase 3: 연결 브릿지 및 검증

- [x] 흐름 비교 엔진(기초)
  - 구현: `logic_consistency_harness()`의 코사인 유사도
- [ ] top-k 문단 + 논리 연결성 고도화
  - 임베딩 기반 top-k 검색을 브릿지 전처리로 연결 필요
- [ ] 시점/인칭 감지기
  - 1인칭/3인칭 및 관찰자 변동 감지 룰 추가 필요
- [ ] 옴니버스/전환점 판별 UX
  - 프론트(`StoryWorkspace`)에 사용자 선택 UI 추가 필요

## Phase 4: 메모리 및 그래프 시각화

- [x] 계층적 요약(Parent-Child) 1차 구현
  - 구현: `/api/agent/hierarchical-summary`
  - 체인: 문단 요약 -> 사건 추출 -> 챕터 요약
- [ ] 임베딩 파이프라인 고도화 (문단 단위 저장 자동화)
  - 현재는 episode chunk 중심, paragraph 단위 인덱싱 추가 필요
- [x] Graph DB 연동 1차 (Neo4j/Cypher)
  - 구현: `backend/app/services/graph_sync.py`
  - 연동: `finalize-episode`, `bible-apply`, `graph-sync/{episode_id}`
- [x] 그래프 온톨로지/쿼리 생성기 1차
  - `graph_ontology()`, `extract_graph_facts()`, Cypher MERGE 동기화
- [x] 데이터 정합성 체크 엔드포인트 1차
  - 구현: `GET /api/agent/graph/sync-check/{story_id}`
- [ ] 하이퍼링크 UI (그래프 노드 -> 원문 앵커 이동)

## Harness Engineering 적용 현황

- [x] Context Injection Harness 1차
  - 구현: `context_builder.build_writer_context`에 `graph_block` 주입
- [x] Logic Consistency Harness (초기 규칙형)
  - 구현: `/api/agent/harness/logic-consistency`
- [x] Conflict Resolution Harness 1차
  - 구현: `/api/agent/harness/conflict-resolution` + `GRAPH_CONFLICT_POLICY`
- [ ] Semantic Routing Harness
  - TODO: 사용자 의도(question/create/revise) 분기 라우터
- [ ] Summary Refinement Harness
  - TODO: 요약 역복원 테스트(요약 -> 사건 복구율 측정)
- [x] Graph-to-Text Harness 1차
  - 구현: `graph_context_text()` (그래프 관계 -> 생성용 자연어 컨텍스트)

## 다음 권장 구현 순서

1. `multi_step` 오케스트레이션 구현 (Phase 2 마무리)
2. 시점/인칭 감지기 + 전환점 사용자 선택 UI (Phase 3)
3. Graph-to-Text + Context Injection 결합 (Phase 4와 Harness 연결)
