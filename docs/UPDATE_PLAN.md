# 소설 집필 에이전트 업데이트 및 고도화 플랜

본 문서는 사용자의 요구사항을 바탕으로 기존 `novel-writing-agent` 프로젝트의 백엔드 구조와 데이터베이스 설계를 어떻게 업데이트할지에 대한 상세 플랜을 담고 있습니다.

## 1. 전체 시스템 아키텍처 개요

기존의 단선적인 생성 방식에서 벗어나, **전역 설정(Background) -> 분석(Question Agent) -> 전략 수립(Generation Strategy) -> 실행 및 검증(Bridge & Pipeline)**의 다단계 에이전트 구조로 전환합니다.

---

## 2. 세부 에이전트 및 프로세스 설계

### 2.1 집필 기본 흐름 (Drafting Workflow)

#### (1) 배경 설정 단계 (Background Setting)
- **목적**: 소설의 대전제(인물 관계, 세계관, 핵심 갈등)를 설정하여 생성 시 일관성 유지.
- **구현**: 
    - `/story` 생성 시 `synopsis` 외에 `world_setting` 필드를 추가하여 텍스트 저장.
    - 입력된 배경 정보를 `StoryBibleEntry`로 자동 분해하여 RAG 및 Graph DB에 선반영.

#### (2) 사용자 초안 입력 및 분석 (Draft Analysis)
- **Question 에이전트**: 
    - `classify_required_elements` 서비스를 강화하여 등장인물 이름, 장소 정보 등이 누락되었는지 체크.
    - 누락 시 사용자에게 질문을 던져 정보를 보강하는 인터렉티브 루프 구현.
- **Generation Strategy 에이전트**:
    - `decide_generation_mode`를 확장하여, 초안의 길이에 따라 '한 번에 생성'할지, '장면 단위로 쪼개어 반복 호출(Incremental Create)'할지 결정.

---

### 2.2 연결 브릿지 및 품질 검증 (Bridge & Verification)

#### (1) 연속성 검사 (Continuity Check)
- **직전 본문과의 자연스러움**: `logic_consistency_harness`를 확장하여 문체 일관성 및 문장 간 연결성 점수 측정.
- **챕터 흐름 위배 여부**: 현재 생성된 내용이 챕터의 `summary`나 설정된 `chapter_events`의 궤적에서 벗어나지 않는지 LLM 판정.
- **Top-K 흐름 비교**: Vector DB에서 가장 유사한 과거 장면들(Top-K)을 가져와 현재 생성 중인 톤과 설정이 충돌하지 않는지 비교 분석.

#### (2) 장면 전환 및 시점 감지
- 새로운 챕터 시작 시:
    - 옴니버스식 구성, 시점 변환(POV Shift), 인칭 전환 여부를 Metadata로 관리.
    - 기존 흐름과 의도적으로 다른 경우(예: 시점 전환) '단절 허용' 태그를 부여하여 검증 로직 우회.

---

### 2.3 과거 장면 되짚기 및 요약 계층 (Memory & Hierarchical Summary)

#### (1) 임베딩 및 검색 가시성
- **단락 단위 임베딩**: 모든 AI 생성물(`EpisodeBody`)을 단락(Paragraph) 단위로 쪼개어 `EpisodeChunk`에 저장.
- **검색 결과 컬러링**: 검색된 Chunk의 유사도나 카테고리에 따라 Frontend에서 컬러를 입힐 수 있도록 `metadata`에 `color_tag` 필드 추가.
- **내용 연결**: 특정 단락 클릭 시 해당 `episode_id`와 `segment_index`를 통해 전체 문맥으로 바로 이동하는 링크 로직 제공.

#### (2) 계층적 요약 구조 (Parent-Child Hierarchy)
- **데이터 구조**:
    - `EpisodeBody` (본문) -> `Paragraph Summary` (단락 요약) -> `Event` (사건) -> `Episode Summary` (챕터 요약) -> `Work Summary` (전체 요약).
    - 각 요약 단계에서 상위/하위 ID를 참조하여 **부모-자식 트리 구조** 형성.
- **사건 중심 요약**: 단순히 텍스트를 줄이는 것이 아니라, 추출된 `chapter_events`를 중심으로 "누가, 무엇을, 왜" 했는지에 집중하여 요약본 생성.

---

## 3. 데이터베이스 및 기술 스택 설계

### 3.1 관계형 DB (PostgreSQL + pgvector)
- **`stories` 테이블**: `world_setting` (Text), `global_rules` (JSONB) 추가.
- **`episode_bodies` 테이블**:
    - `parent_id`: 상위 요약본이나 참조 본문 ID.
    - `meta_tags`: POV 정보, 시간대, 검색용 컬러 코드 등을 담은 JSONB.
- **`episode_chunks` 테이블**: `embedding` 외에 `category` (인물/상황/사건) 필드 추가.

### 3.2 그래프 DB (Neo4j)
- **3D 그래프 시각화**: 인물(CHAR), 상황(SITUATION), 사건(EVENT) 노드 간의 관계망 구축.
- **추가 노드 타입**: `SITUATION` (특정한 정황이나 분위기) 노드 타입을 추가하여 사건의 배경 설명 보강.
- **관계성 확장**: `TRIGGERED_BY`, `LEADS_TO`, `INVOLVED_IN` 등의 관계 타입을 세분화하여 인과관계 명확화.

---

## 4. 구현 우선순위 (Roadmap)

1.  **Phase 1: 데이터 스키마 확장** - `world_setting`, `meta_tags`, `parent-child` 관계 필드 추가.
2.  **Phase 2: Question & Strategy 에이전트 고도화** - 초안 분석 로직 정교화.
3.  **Phase 3: 계층적 요약 및 브릿지 검증** - 생성된 본문을 요약하고 이전 문맥과 대조하는 파이프라인 완성.
4.  **Phase 4: 그래프 DB 시각화 최적화** - Neo4j 데이터를 3D 라이브러리(React-Force-Graph 등)와 연동할 수 있는 API 강화.

---

위 플랜에 대해 검토해 주시면, 세부 코드 수정 작업에 착수하도록 하겠습니다.
