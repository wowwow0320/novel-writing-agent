# 전체 코드 흐름 정리 (Novel Writing Agent)

이 문서는 **사용자 요청이 프론트엔드에서 백엔드·DB·LLM까지 어떻게 흐르는지**를 한눈에 볼 수 있게 정리합니다.  
환경 변수·Docker 세부는 `PROJECT_REFERENCE.md`와 루트 `README.md`를 참고하면 됩니다.

---

## 1. 시스템 구성 요약

| 구분 | 기술 | 역할 |
|------|------|------|
| 프론트엔드 | React + Vite + React Router | 작품·챕터 편집, API 호출 |
| 백엔드 | FastAPI (비동기 SQLAlchemy) | REST API, LLM 호출, RAG |
| 데이터베이스 | PostgreSQL + pgvector | 작품/챕터/본문/바이블/청크·벡터 저장 |
| AI | OpenAI 또는 Gemini (`app/services/llm.py`) | 채팅 완성, (선택) 임베딩 |
| 임베딩 | OpenAI 기본(`text-embedding-3-large`·`OPENAI_API_KEY`) / Ollama / Gemini / none (`EMBEDDING_PROVIDER`) | RAG용 벡터 |
| 벡터 차원 | `EMBEDDING_DIMENSION`(기본 3072, `app/config.py`) | `pgvector` 컬럼·Alembic(`004_vector_3072_hierarchy_summaries` 등)과 반드시 일치 |

**HTTP 경로**

- **로컬 개발**: 브라우저 → Vite (`/api` 프록시) → `frontend/vite.config.ts`의 `server.proxy['/api'].target`이 가리키는 백엔드(저장소 기준 `http://127.0.0.1:8001`). 실제 포트는 백엔드 실행 방식에 맞춰 동일하게 둡니다.
- **Docker**: 브라우저 → Nginx (`/api/` 프록시) → 백엔드 컨테이너 `.../api/...`

프론트의 모든 API 호출은 `frontend/src/api.ts`에서 **`/api`를 base**로 사용합니다.

---

## 2. 백엔드 앱 부팅과 라우터 마운트

1. `uvicorn app.main:app` → `backend/app/main.py`의 `FastAPI` 인스턴스 생성  
2. CORS: `Settings.cors_allow_origins` (쉼표 구분)  
3. 라우터 등록 (모두 **`/api` 접두사** 아래):

| 파일 | prefix | 태그 |
|------|--------|------|
| `app/routers/stories.py` | `/stories` | stories |
| `app/routers/episodes.py` | `/stories/{story_id}/episodes` | episodes |
| `app/routers/story_bible.py` | `/stories/{story_id}/bible` | story_bible |
| `app/routers/agent.py` | `/agent` | agent |

4. 헬스: `GET /api/health` → `{"status":"ok"}`

5. DB 세션: `app/database.py`의 `get_db` 의존성 → 각 라우트에서 `AsyncSession` 사용

---

## 3. 데이터 모델과 저장 구조

정의: `backend/app/models.py`

```text
Story (작품)
  │   work_summary — 챕터 요약을 모은 작품 전체 메타 요약
  ├── episodes[] → Episode (챕터)
  │       ├── summary — 챕터 메타 요약 (블록 요약·사건 추출 기반)
  │       ├── chapter_events — 챕터 단위 사건 JSON 배열
  │       ├── bodies[] → EpisodeBody (본문 블록, segment_index 순)
  │       │       body_summary — 블록 단위 요약 (계층의 leaf)
  │       └── chunks[] → EpisodeChunk (RAG용 텍스트 조각 + embedding, vector 차원은 .env와 Alembic 004 일치)
  └── bible_entries[] → StoryBibleEntry (설정 노트 + embedding; 추출 LLM은 OPENAI_BIBLE_MODEL 기본 gpt-5-nano)
```

- **본문의 단일 진실**: `episode_bodies` 행들. API의 `Episode.ai_content`는 **합성 프로퍼티**(`combine_episode_bodies`).
- **연결 방식**: `EpisodeBody.link_to_previous` — `continuous` / `omnibus` (첫 블록은 `null`). 합치기 로직은 `app/services/episode_text.py`.
- **계층 요약**: `POST /api/agent/finalize-episode/{id}` 가 블록별 요약(`EpisodeBody.body_summary`) → `chapter_events` + `Episode.summary` → RAG 청크 갱신 → `Story.work_summary`(rollup) 순으로 갱신하고, `graph_enabled`이면 Neo4j 동기화를 시도합니다.
- **메모**: `Episode.raw_memory` — 작가 메모; AI 확장 시 프롬프트에 포함.
- **Hybrid DB(선택)**: Postgres가 원본(Source of Truth)이고, `graph_enabled=true`일 때 Neo4j에 관계를 복제합니다. 집필 컨텍스트의 `graph_block`은 `app/services/graph_sync.py`의 `graph_context_text`로 요약 주입됩니다.

---

## 4. 프론트엔드 화면 흐름

### 4.1 라우팅 (`frontend/src/App.tsx`)

| 경로 | 컴포넌트 |
|------|----------|
| `/` | `Dashboard` — 작품 목록·생성 |
| `/story/:storyId` | `StoryWorkspace` — 해당 작품 집필 공간 |
| 그 외 | `/`로 리다이렉트 |

### 4.2 API 클라이언트 (`frontend/src/api.ts`)

- `fetch('/api' + path, ...)` — JSON 요청/응답, 에러 시 `detail` 파싱.
- `api.stories.*`, `api.episodes.*`, `api.bible.*`, `api.agent.*` 로 백엔드와 대부분 1:1 대응.

**`api.agent`에 포함된 것**: `expand-draft`, `finalize-episode`, `bible-extract` / `bible-apply` / `bible-commit`, `bridge`, `rag-search`, `consistency`, `style-transfer`, `export`, 그리고 그래프 보조용 `graph/ontology`, `graph/subgraph/...`, `graph-sync/{episode_id}`, `graph/sync-check/...`.

**아직 `api.ts`에 없는 백엔드 전용·실험 엔드포인트**: `POST /api/agent/foundation/analyze`, `POST /api/agent/decision`, `POST /api/agent/hierarchical-summary`, `POST /api/agent/harness/*` — UI나 스크립트에서 쓰려면 동일 패턴으로 `fetch` 래퍼를 추가하면 됩니다.

### 4.3 작품 워크스페이스 (`StoryWorkspace.tsx`) — 대표 사용자 시나리오

1. **마운트** → `api.stories.get`, `api.episodes.list`, `api.bible.list` 병렬 호출 후 상태 갱신  
2. **챕터 선택** → 해당 `Episode`의 `raw_memory`, `bodies`를 로컬 상태로 복원(블록이 없으면 `ai_content`로 첫 블록 초기화)  
3. **저장** (`saveEpisode`)  
   - `api.episodes.replaceBodies` → `PUT .../episodes/{id}/bodies`  
   - `api.episodes.patch` → `PATCH .../episodes/{id}` (`raw_memory`)  
   - 토글 **「저장 시 설정 노트 자동 반영」**이 켜져 있으면 이어서 `api.agent.bibleApply` → `POST /api/agent/bible-apply/{episodeId}` (DB 본문 기준 LLM 추출·임베딩·선택적 그래프 동기화)  
4. **설정 노트 미리보기** → 로컬에서 합친 본문으로 `api.agent.bibleExtract` → 편집 없이 확정하려면 `api.agent.bibleCommit`  
5. **AI 초안** → `api.agent.expand` → `POST /api/agent/expand-draft` (작품 `genre`를 `genre_override`로 넘김) → `ai_content`를 **현재 활성 블록**에만 반영(저장은 사용자가 별도 수행)  
6. **챕터 마무리** (`runFinalize`) → 먼저 `saveEpisode({ skipAutoBible: true })`로 디스크와 동기화 → `api.agent.finalize` → 자동 바이블 옵션이 켜져 있으면 `bibleApply`  
7. **브릿지** → 직전 화 요약·이전 블록 또는 이전 화 끝 발췌(`buildBridgeAnchor`) + 메모로 `api.agent.bridge`  
8. **RAG** → `api.agent.rag`  
9. **일관성** → 범위 `chapter`면 현재 챕터 id를 `focus_episode_id`로 `api.agent.consistency`  
10. **문체** → `api.agent.style`  
11. **보내기** → `api.agent.export` (blob)

그래프 API(`graphOntology` 등)는 `api.ts`에만 정의되어 있고, 현재 `StoryWorkspace` UI에서는 호출하지 않습니다.

---

## 5. 백엔드 REST API 흐름 (라우터별)

### 5.1 Stories — `backend/app/routers/stories.py`

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/api/stories` | 작품 생성 |
| GET | `/api/stories` | 목록 |
| GET | `/api/stories/{id}` | 단건 |
| PATCH | `/api/stories/{id}` | 시놉시스·장르·문체 지침 등 수정 |
| DELETE | `/api/stories/{id}` | 삭제 (CASCADE로 하위 데이터 정리) |

### 5.2 Episodes — `backend/app/routers/episodes.py`

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/api/stories/{story_id}/episodes` | 챕터 생성; `ai_content`가 있으면 첫 `EpisodeBody`로 저장 |
| GET | `.../episodes` | 목록 (`bodies` 포함) |
| GET | `.../episodes/{episode_id}` | 단건 |
| PUT | `.../episodes/{episode_id}/bodies` | 본문 블록 배열 **전체 교체** (`replace_episode_bodies`) |
| PATCH | `.../episodes/{episode_id}` | `raw_memory`, `summary`, `status` 등 |
| DELETE | `.../episodes/{episode_id}` | 삭제 |

### 5.3 Story Bible — `backend/app/routers/story_bible.py`

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/api/stories/{story_id}/bible` | 수동 항목 추가 → `rag.embed_bible_entries` |
| GET | `.../bible` | 목록 |
| PATCH | `.../bible/{entry_id}` | 수정 → 임베딩 갱신 |
| DELETE | `.../bible/{entry_id}` | 삭제 |

---

## 6. Agent 라우터 — AI·RAG·보내기 (`backend/app/routers/agent.py`)

공통: 대부분 `AsyncSession`으로 Story/Episode를 읽고, `app/services/llm.py`의 `complete_chat` 또는 `embed_texts`를 호출합니다.

### 6.1 집필 컨텍스트 조립 — `app/services/context_builder.py`

`build_writer_context(db, story_id, chapter_num)`이 반환하는 것:

- `synopsis`, `genre`, `style_guide`, `language` — `Story`에서
- `bible_block` — `StoryBibleEntry`를 `format_bible`로 문자열화
- `graph_block` — `get_settings().graph_enabled`일 때 `graph_sync.graph_context_text`로 만든 Neo4j 요약 텍스트(실패 시 빈 문자열)
- `prev_summary` — 직전 챕터(`chapter_num - 1`)의 `summary`
- `sliding` — `sliding_window_context`: 오래된 챕터는 **요약만**, 최근 N화는 **전문**을 프롬프트용 문자열로 결합 (`rag_recent_full_episodes`)

**`/api/agent/expand-draft`** 흐름:

1. `Episode` 로드 → `story_id`, `chapter_num` 확보  
2. `build_writer_context`  
3. 요청의 `genre_override`가 있으면 그 장르, 없으면 스토리 장르로 `llm.genre_writer_role` 등 반영 후 `prompts.expand_draft_system` / `expand_draft_user`(시놉·바이블·**graph_block**·이전 요약·슬라이딩·메모) 구성  
4. `llm.complete_chat` → `ExpandDraftResponse(ai_content=..., context_used=...)` (DB 자동 저장 없음)

### 6.2 Neo4j·정합성 보조 — `app/services/graph_sync.py`

에이전트 라우터가 여기서 가져오는 대표 함수:

- `graph_context_text` — 집필 프롬프트용 그래프 요약
- `sync_episode_text_to_graph` / `sync_bible_entries_to_graph` — 본문·바이블 반영 시 MERGE
- `graph_subgraph`, `graph_ontology`, `graph_counts` — 조회·스키마·개수
- `conflict_resolution_harness` — Postgres vs Graph 상태와 `graph_conflict_policy` 기반 정책 시뮬레이션

### 6.3 챕터 확정 — `POST /api/agent/finalize-episode/{episode_id}`

1. `full_episode_writing_text(ep)` 로 본문 확보(비어 있으면 400)  
2. `story_pipeline.hierarchical_from_block_texts` — 블록별 문단 요약 → 사건 → 챕터 요약 체인  
3. 각 `EpisodeBody.body_summary`, `Episode.summary`, `Episode.chapter_events` 갱신  
4. `rag.upsert_chunks_for_episode` — 기존 청크 삭제 후 분할·임베딩·`episode_chunks` 저장  
5. `rollup_story_work_summary` — `Story.work_summary` (실패해도 앞 단계 데이터는 유지, 로그만)  
6. `graph_enabled`이면 `sync_episode_text_to_graph` 시도(실패 시 경고 로그, 트랜잭션은 커밋)

### 6.4 바이블 추출·적용

| 엔드포인트 | 동작 |
|------------|------|
| `POST /api/agent/bible-extract` | 요청의 `ai_content`(프론트는 보통 **로컬 편집본 합본**)으로 JSON 배열 추출만 수행 |
| `POST /api/agent/bible-apply/{episode_id}` | **DB에 저장된** 본문으로 추출 → `_persist_bible_entries` → `embed_bible_entries` → `graph_enabled`이면 `sync_bible_entries_to_graph` |
| `POST /api/agent/bible-commit/{episode_id}` | 클라이언트 `entries`를 그대로 저장·임베딩 (LLM 없음, **그래프 동기화 없음**) |

프롬프트: `prompts.bible_update_*` + `json_extract.parse_llm_json_array` (`bible_extract`/`bible_apply`는 `llm.complete_chat_bible`)

### 6.5 브릿지·RAG·일관성·문체·보내기

- **Bridge** `POST /api/agent/bridge`: (선택) `story_id`로 바이블 힌트 로드 → `bridge_system` / `bridge_user` (`anchor_excerpt` 포함)
- **RAG** `POST /api/agent/rag-search`: `rag.search_rag_merged` — 벡터 검색 우선, 실패 시 pg_trgm/ILIKE 폴백
- **Consistency** `POST /api/agent/consistency`: 바이블 + 에피소드 발췌(또는 포커스 챕터 전체)로 LLM 검토
- **Style transfer** `POST /api/agent/style-transfer`
- **Export** `POST /api/agent/export`: `export.build_story_text` → txt/pdf/epub 바이트 응답

### 6.6 컨텍스트 미리보기

- `GET /api/agent/context-preview/{story_id}?chapter_num=...` — `build_writer_context` 결과 JSON (디버깅·UI 확장용)

### 6.7 스토리 파이프라인 (추가 모듈) — `app/services/story_pipeline.py`

`finalize-episode`는 내부적으로 여기의 `hierarchical_from_block_texts`, `events_for_jsonb`, `rollup_story_work_summary`를 사용합니다. 아래는 **별도 HTTP로도** 노출된 도우미입니다.

| 엔드포인트 | 설명 |
|------------|------|
| `POST /api/agent/foundation/analyze` | 초안 → 세계관 JSON 스키마에 맞춘 추출 + who/where/what 누락 판별 |
| `POST /api/agent/decision` | 초안 길이·문장 수·복잡도로 `single_pass` / `multi_step` 제안 |
| `POST /api/agent/hierarchical-summary` | 문단 요약 → 사건 추출 → 챕터 요약 (계층 요약 체인) |
| `POST /api/agent/harness/logic-consistency` | 두 텍스트 간 단어 기반 코사인 + 간단 규칙 이슈 |
| `POST /api/agent/harness/conflict-resolution` | Postgres vs Graph 충돌 상태 해결 정책 하네스(기본 정책은 `graph_conflict_policy`) |
| `GET /api/agent/graph/ontology` | 그래프 스키마(노드/관계 타입) |
| `POST /api/agent/graph-sync/{episode_id}` | 에피소드 본문에서 Neo4j 수동 동기화 |
| `GET /api/agent/graph/subgraph/{story_id}` | 3D 시각화용 노드/엣지 조회 |
| `GET /api/agent/graph/sync-check/{story_id}` | Postgres/Graph 정합성 점검 카운트 |

프롬프트 일부: `app/services/prompts.py`의 `foundation_*`, `question_*`, `paragraph_summary_*`, `event_*`, `chapter_summary_*`

---

## 7. RAG 상세 흐름 (`app/services/rag.py`)

1. **바이블 임베딩 문서**: `[카테고리] 이름\n설명` 형태 (`bible_document_for_embed`)  
2. **에피소드 청크**: `upsert_chunks_for_episode`에서 본문을 고정 길이+오버랩으로 자름 → `llm.embed_texts` (provider가 none이면 벡터 없음)  
3. **검색** `search_rag_merged`:  
   - 임베딩 사용 시: 쿼리 임베딩 → `<=>` 코사인 거리 기반 `episode_chunks` / `story_bible` UNION 성격의 병합 정렬  
   - 실패 시: `pg_trgm` 유사도  
   - 그다음: ILIKE 키워드 폴백  
4. **에이전트 라우터**의 `rag-search`는 병합 결과가 비면 `keyword_fallback_episodes` / `keyword_fallback_bible` 사용

---

## 8. LLM·임베딩 (`app/services/llm.py`)

- **`complete_chat(system, user, temperature)`**  
  - `AI_PROVIDER`: `openai` → Chat Completions API  
  - `gemini` → `google.generativeai` (async 우선, 실패 시 sync 재시도)  
- **`embed_texts(texts)`**  
  - `EMBEDDING_PROVIDER`: `ollama` / `openai` / `gemini` / `none`  
  - 차원은 `embedding_dimension`(환경 변수 `EMBEDDING_DIMENSION`)과 DB `Vector(...)` 정의·Alembic 리비전이 일치해야 함

---

## 9. 한 장으로 보는 “저장 한 번” 시퀀스 (StoryWorkspace 기준)

```text
[사용자] 편집 (raw_memory + bodies)
    → PUT /stories/{sid}/episodes/{eid}/bodies
    → PATCH /stories/{sid}/episodes/{eid}  (raw_memory)
    → (옵션, UI 토글 ON) POST /agent/bible-apply/{eid}
          → DB 본문으로 LLM JSON 배열 추출
          → story_bible INSERT
          → embed_bible_entries
          → (graph_enabled) sync_bible_entries_to_graph
```

**이후 검색 품질을 올리려면** 사용자가 `finalize-episode`를 실행해 블록 요약·`summary`·`chapter_events`·`episode_chunks`·(옵션) 그래프 동기화·`work_summary`까지 맞추는 흐름이 이어집니다. 워크스페이스의 「요약·인덱싱」은 그 전에 조용히 `saveEpisode(skipAutoBible)`로 서버 본문을 최신화합니다.

---

## 10. 관련 문서

| 파일 | 내용 |
|------|------|
| `README.md` | 실행 방법, 디렉터리 개요 |
| `PROJECT_REFERENCE.md` | 파일별 상세, API 표, 환경 변수 |
| `docs/DATABASE_ERD.md` | DB 관계 (있는 경우) |
| `docs/AGENT_PIPELINE_TODO.md` | 에이전트 파이프라인 로드맵·구현 체크리스트 |

---

## 11. 확장 시 권장 연결 지점

- **UI에 새 API 노출**: `frontend/src/api.ts` + `StoryWorkspace.tsx` (또는 별도 페이지)  
- **생성 전 컨텍스트 주입**: `context_builder.build_writer_context` 또는 `expand_draft_*` 프롬프트 수정  
- **DB 스키마 변경**: `app/models.py` + `alembic/versions/` 새 리비전  
- **RAG 품질**: `rag.py`의 청크 크기·검색 쿼리, `EMBEDDING_PROVIDER` 설정
- **그래프**: `graph_sync.py` + `GRAPH_ENABLED` / Neo4j 관련 env (`GRAPH_CONFLICT_POLICY` 등)

이 문서는 코드 변경에 따라 수동으로 맞춰 주는 것이 좋습니다. 엔드포인트 추가 시 **섹션 5~6**을 함께 갱신하면 전체 흐름이 유지됩니다.
