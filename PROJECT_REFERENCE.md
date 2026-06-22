# 프로젝트 참조 문서 (파일·로직·환경·남은 작업)

이 문서는 `novel-writing-agent` 저장소의 **모든 소스 파일과 폴더**, **데이터 흐름**, **REST API**, **사용자가 직접 해야 할 일**, **AI(코딩 어시스턴트)에게 줄 지시 예시**, **venv / conda / Docker 사용 관계**를 한곳에 정리합니다.  
(제외: `backend/.venv`, `frontend/node_modules` 등 의존성 설치 결과물)

---

## 1. 환경 구성: Docker vs venv vs 아나콘다

### 1.1 Docker Compose (일체 실행)

| 항목 | 내용 |
|------|------|
| **`docker-compose.yml`** | 서비스 **3개**: `db`(PostgreSQL 16 + pgvector), `backend`(FastAPI), `frontend`(Nginx + React 빌드). |
| **웹 UI** | `http://localhost:8080` — Nginx가 정적 파일을 서빙하고 **`/api/`** 를 `http://backend:8000/api/` 로 **리버스 프록시**. |
| **API 직접** | `http://localhost:8000` (호스트에서 디버깅·curl용). |
| **Postgres (호스트에서 접속)** | `localhost:5433` → 컨테이너 내부 `5432` |
| **Compose 내부 DB 호스트명** | 서비스 이름 **`db`**, 포트 **5432** |
| **백엔드 DB URL** | Compose `environment`로 고정: `postgresql+asyncpg://novel:novel@db:5432/novel_agent` (`backend/.env`의 `DATABASE_URL`보다 우선). |
| **Alembic (컨테이너)** | 환경변수 **`ALEMBIC_SYNC_URL`** = `postgresql+psycopg://novel:novel@db:5432/novel_agent`. `alembic/env.py`가 이 값이 있으면 `alembic.ini` URL 대신 사용. |
| **시크릿·설정** | 프로젝트 **루트** `.env` — Compose가 변수 치환에 사용 (`GEMINI_API_KEY` 등). 템플릿: **`.env.example`**. |
| **백엔드 시작 순서** | `docker-entrypoint.sh`: TCP로 `db:5432` 대기 → `alembic upgrade head` → `uvicorn`. |
| **이미지 베이스** | 백엔드: `python:3.12-slim-bookworm`. 프론트: multi-stage `node:22-alpine` 빌드 + `nginx:1.27-alpine`. |

### 1.2 Python 백엔드 (로컬)

| 방식 | 프로젝트에서의 역할 |
|------|---------------------|
| **`python -m venv .venv`** | 로컬 개발 시 `backend/requirements.txt` 설치. Docker 이미지는 별도로 Dockerfile 안에서 pip 설치. |
| **Anaconda / Miniconda** | **conda 환경 파일은 없음.** conda 안에서도 `pip install -r backend/requirements.txt` 로 맞출 수 있음. |

### 1.3 Node.js (프론트)

- **npm** (`package.json`). Docker 빌드 시 이미지 내부에서 `npm ci` / `npm run build`.
- 로컬 개발: `npm run dev` + Vite 프록시 `/api` → `127.0.0.1:8000`.

---

## 2. 저장소 루트 파일

| 파일 | 역할 |
|------|------|
| `README.md` | 개요, 디렉터리 트리, Docker/로컬 실행, `requirements.txt` 갱신. |
| `PROJECT_REFERENCE.md` | 본 문서. |
| `.env.example` | Docker Compose용 변수 템플릿 → 루트 `.env` 로 복사. |
| `.gitignore` | `backend/.venv`, `backend/.env`, **루트 `.env`**, `node_modules`, `dist` 등. |
| `docker-compose.yml` | `db`, `backend`, `frontend` 서비스 및 `novel_pgdata` 볼륨. |

### 2.1 `backend/Dockerfile`

- `python:3.12-slim-bookworm`, `WORKDIR /app`.
- `requirements.txt` 설치 후 `alembic.ini`, `alembic/`, `app/` 복사.
- `docker-entrypoint.sh` 를 엔트리포인트로 실행, 포트 8000.

### 2.2 `backend/docker-entrypoint.sh`

- `DB_HOST`/`DB_PORT` (기본 `db`/`5432`)까지 소켓 연결 대기(최대 60초).
- `ALEMBIC_SYNC_URL` 기본값으로 동기 URL 설정 후 `alembic upgrade head`.
- `uvicorn app.main:app --host 0.0.0.0 --port 8000` 실행.

### 2.3 `backend/.dockerignore`

- `.venv`, `.env`, `__pycache__` 등 빌드 컨텍스트에서 제외.

### 2.4 `frontend/Dockerfile`

- **stage `build`**: `npm ci`, `npm run build` (TypeScript + Vite).
- **stage 최종**: `nginx:1.27-alpine`, `nginx.conf` 와 `dist/` 복사, 포트 80.

### 2.5 `frontend/nginx.conf`

- `location /api/` → `proxy_pass http://backend:8000/api/;` (Compose 네트워크에서 서비스명 `backend` 사용).
- SPA: `location /` 에 `try_files $uri $uri/ /index.html;`.

### 2.6 `frontend/.dockerignore`

- `node_modules`, `dist` 등 제외.

---

## 3. 백엔드 (`backend/`)

### 3.1 `requirements.txt`

- **`pip freeze` 결과로 버전이 고정**되어 있습니다. 주석에 설치 방법과 Python 3.14 소스 빌드 시 `PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1` 힌트가 있습니다.
- **갱신 절차**: 가상환경 활성화 → 패키지 조정 → `pip freeze > requirements.txt` → 필요 시 상단 주석 복구.

### 3.2 환경 변수 파일

| 파일 | 용도 |
|------|------|
| **프로젝트 루트 `.env`** | **Docker Compose** 가 변수 치환에 사용. `docker-compose.yml`의 `backend.environment`에 `${VAR}` 로 전달. **git에 커밋하지 않음.** 템플릿: 루트 `.env.example`. |
| **`backend/.env`** | **로컬에서 uvicorn** 실행할 때 `Settings`가 읽음 (`database_url` 등). Docker 백엔드는 Compose가 `DATABASE_URL` 등을 직접 넣으므로 **반드시 backend/.env가 있을 필요는 없음** (없어도 됨). 템플릿: `backend/.env.example`. |

| 변수 | 의미 |
|------|------|
| `DATABASE_URL` | async SQLAlchemy (`postgresql+asyncpg://...`). 로컬은 보통 `localhost:5433`. |
| `AI_PROVIDER` | `gemini` 또는 `openai`. |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | Gemini 사용 시. |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | OpenAI 사용 시. |
| `EMBEDDING_PROVIDER` | 기본 `openai` / `none` / `gemini` / `ollama`(bge-m3). |
| `OPENAI_EMBED_MODEL` | OpenAI 임베딩 모델명. 기본 `text-embedding-3-large` (`dimensions=EMBEDDING_DIMENSION`). |
| `OPENAI_BIBLE_MODEL` | 바이블 JSON 추출 전용 채팅 모델. 기본 `gpt-5-nano` (`complete_chat_bible`). |
| `EMBEDDING_DIMENSION` | **DB `vector(...)` 차원과 일치.** 마이그레이션 `004` 이후 기본 **3072** (OpenAI 3-large 전폭). |
| `RAG_RECENT_FULL_EPISODES` | 슬라이딩 윈도우 최근 전문 에피소드 개수. |
| `SUMMARY_MAX_CHARS` | 요약 프롬프트 힌트. |
| `CORS_ALLOW_ORIGINS` | **쉼표 구분** 허용 Origin 문자열. Docker Nginx·로컬 Vite 등. |

`ALEMBIC_SYNC_URL` 은 주로 **Docker 엔트리포인트/Compose**에서만 설정(로컬은 `alembic.ini` 또는 동일 변수로 오버라이드).

### 3.3 Alembic

| 파일 | 역할 |
|------|------|
| `alembic.ini` | 로컬 기본 동기 URL: `postgresql+psycopg://novel:novel@localhost:5433/novel_agent` |
| `alembic/env.py` | 환경변수 **`ALEMBIC_SYNC_URL`** 이 있으면 이를 `sqlalchemy.url` 로 사용(온라인/오프라인 모두). Docker·CI에서 `db:5432` 연결에 사용. |
| `alembic/script.py.mako` | 새 리비전 파일 템플릿. |
| `alembic/versions/001_initial.py` | `CREATE EXTENSION vector`, 테이블·ENUM·초기 `Vector(1024)` 컬럼 생성. |
| `alembic/versions/004_vector_3072_hierarchy_summaries.py` | 벡터 **3072** + `body_summary` / `chapter_events` / `work_summary` 컬럼. |

**앱 런타임**은 `asyncpg` + `DATABASE_URL`, **마이그레이션**은 `psycopg`(동기)로 같은 DB에 접속합니다.

### 3.4 `app/main.py`

- `FastAPI` 인스턴스 생성, 제목 설정.
- **CORS**: `get_settings().cors_allow_origins` 를 쉼표로 split 한 목록. 환경변수 **`CORS_ALLOW_ORIGINS`** 로 덮어쓰기 가능 (`config.cors_allow_origins`). 기본에 `localhost:8080`(Docker Nginx), `5173`(로컬 Vite) 포함.
- 라우터 prefix `/api` 로 마운트: `stories`, `episodes`, `story_bible`, `agent`.
- `GET /api/health` → `{"status":"ok"}`.

### 3.5 `app/config.py`

- `get_settings()` 캐시된 `Settings` 싱글톤.
- DB URL, AI/임베딩 제공자, 모델명, RAG·요약 파라미터, **`cors_allow_origins`** (문자열, 쉼표 구분 Origin 목록).

### 3.6 `app/database.py`

- `create_async_engine(settings.database_url)`.
- `async_sessionmaker` → `get_db()` 의존성 제너레이터 (FastAPI 라우트에서 `AsyncSession` 주입).
- `Base = DeclarativeBase` (모델 베이스).

### 3.7 `app/models.py`

| 모델 | 테이블 | 주요 필드·관계 |
|------|--------|----------------|
| `Story` | `stories` | `title`, `genre`, `synopsis`, `style_guide`, `language`, `created_at`. `episodes`, `bible_entries` 관계. |
| `Episode` | `episodes` | `story_id`, `chapter_num`, `raw_memory`, `ai_content`, `summary`, `status` (`draft`/`completed`). `chunks` 관계. |
| `StoryBibleEntry` | `story_bible` | `category` (ENUM `CHAR`/`LOC`/`ITEM`/`EVENT`), `name`, `description`, **DB 컬럼명 `metadata`** → Python 속성 `extra`, 선택 `embedding` (`Vector(dim)`). |
| `EpisodeChunk` | `episode_chunks` | `story_id`, `episode_id`, `chunk_index`, `content`, `embedding`. |

`embedding_dimension`은 모듈 로드 시 `get_settings().embedding_dimension`으로 `Vector` 차원 결정.

### 3.8 `app/schemas.py`

- Pydantic v2 스키마: `StoryCreate/Update/Out`, `Episode*`, `Bible*` (바이블 출력 시 `metadata` ↔ ORM `extra` 별칭).
- 에이전트용: `ExpandDraftRequest/Response`, `BibleExtract*`, `Bridge*`, `RAGSearch*`, `Consistency*`, `StyleTransfer*`, `ExportRequest` 등.

### 3.9 `app/routers/stories.py`

- `POST /api/stories` 생성, `GET` 목록, `GET /{story_id}`, `PATCH`, `DELETE`.

### 3.10 `app/routers/episodes.py`

- Prefix: `/api/stories/{story_id}/episodes`
- `POST` 생성, `GET` 목록(챕터 순), `GET /{episode_id}`, `PATCH`, `DELETE`.

### 3.11 `app/routers/story_bible.py`

- Prefix: `/api/stories/{story_id}/bible`
- `POST` 생성 (`metadata` → DB `metadata` 컬럼, ORM `extra`).
- `GET` 목록, `PATCH /{entry_id}`, `DELETE`.

### 3.12 `app/routers/agent.py` (오케스트레이션 허브)

| 메서드 | 경로 | 로직 요약 |
|--------|------|-----------|
| POST | `/api/agent/expand-draft` | 대상 `Episode` 로드 → `build_writer_context`(시놉시스·바이블·그래프 컨텍스트·직전 요약·슬라이딩 윈도우) 조합 → 장르 `genre_writer_role` → `expand_draft_*` 프롬프트 → `llm.complete_chat` → 본문 반환 (DB 자동 저장 없음). |
| POST | `/api/agent/finalize-episode/{episode_id}` | 본문 블록 기준 계층 요약(블록 요약·사건·챕터 요약) 저장 + `Story.work_summary` 롤업 + `rag.upsert_chunks_for_episode` + (옵션) Neo4j 동기화. |
| POST | `/api/agent/bible-extract` | 본문으로 바이블 추출 프롬프트 → JSON 배열 파싱 → **DB에 쓰지 않고** `entries`만 반환. |
| POST | `/api/agent/bible-apply/{episode_id}` | 해당 에피소드 본문으로 추출 → 파싱 항목 `StoryBibleEntry` 추가 + 임베딩 + (옵션) Neo4j 엔티티 동기화. |
| GET | `/api/agent/graph/ontology` | 그래프 온톨로지(노드/관계 타입) 반환. |
| POST | `/api/agent/graph-sync/{episode_id}` | 선택 에피소드 본문에서 Neo4j 수동 동기화. |
| GET | `/api/agent/graph/subgraph/{story_id}` | 3D 시각화용 그래프 노드/엣지 반환. |
| GET | `/api/agent/graph/sync-check/{story_id}` | Postgres vs Graph 정합성 점검 카운트. |
| POST | `/api/agent/harness/conflict-resolution` | Postgres/Graph 충돌 상태 해결 정책 하네스. |
| POST | `/api/agent/bridge` | 선택적 `story_id`로 바이블 힌트 → A요약+B메모 브리지 프롬프트 → 제안 텍스트. |
| POST | `/api/agent/rag-search` | `rag.search_similar` (임베딩 있으면 벡터, 없으면 ILIKE); 결과 없으면 `keyword_fallback_episodes`. |
| POST | `/api/agent/consistency` | 최근 에피소드 본문 발췌 + 바이블 + 시놉시스 → 일관성 검토 프롬프트. |
| POST | `/api/agent/style-transfer` | 문체 리라이트 프롬프트. |
| POST | `/api/agent/export` | 스토리 전체 텍스트 조립 → `txt` / `pdf` / `epub` 바이너리 응답. |
| GET | `/api/agent/context-preview/{story_id}?chapter_num=` | 디버그용 컨텍스트 딕셔너리 JSON. |

### 3.13 `app/services/llm.py`

- `complete_chat(system, user, temperature)`: `AI_PROVIDER`에 따라 OpenAI Chat Completions 비동기 또는 Gemini `GenerativeModel` + `generate_content_async`.
- `complete_chat_bible(...)`: 바이블/그래프 추출 전용 OpenAI 모델(`OPENAI_BIBLE_MODEL`, 기본 `gpt-5-nano`) 우선.
- `embed_texts`: `ollama`는 `OLLAMA_EMBED_MODEL`(기본 bge-m3), `openai`는 `OPENAI_EMBED_MODEL`(기본 `text-embedding-3-large`)+`dimensions=EMBEDDING_DIMENSION`, `gemini`는 `text-embedding-004`(차원 불일치 시 런타임 오류).
- `genre_writer_role(genre)`: 한글/영문 키워드로 역할 문자열 매핑 (로맨스·스릴러 등).

### 3.14 `app/services/prompts.py`

- 1단계 확장: `expand_draft_system` / `expand_draft_user` (시놉시스, 바이블, 직전 요약, 슬라이딩 블록, 메모).
- 바이블 업데이트: `bible_update_system` / `bible_update_user` (JSON 배열만 출력 지시).
- 브리지: `bridge_system` / `bridge_user`.
- 일관성: `consistency_system` / `consistency_user`.
- 문체: `style_transfer_system` / `style_transfer_user`.
- 요약: `summary_system` / `summary_user`.

### 3.15 `app/services/context_builder.py`

- `load_story_episodes`: 스토리 + 에피소드 정렬 로드.
- `fetch_bible`, `format_bible`: 바이블 목록 텍스트화.
- `sliding_window_context`: 현재 챕터 **이전** 에피소드 중 최근 N개는 본문 합본(`episode_bodies`) 전문, 그보다 오래된 것은 `summary`만 나열.
- `prev_chapter_summary`: `chapter_num - 1` 요약.
- `build_writer_context`: 위 + Neo4j Graph-to-Text(`graph_block`)를 묶어 에이전트 확장 dict 반환.

### 3.16 `app/services/rag.py`

- `upsert_chunks_for_episode`: 기존 청크 삭제 → 본문을 길이·오버랩으로 자름 → 임베딩 채움 → `EpisodeChunk` 행 삽입.
- `search_similar`: 쿼리 임베딩 후 `<=>` 거리 정렬 SQL (문자열 벡터 리터럴); 실패/미설정 시 청크 `ILIKE`.
- `keyword_fallback_episodes`: 에피소드 `ai_content`/`summary` ILIKE.

### 3.17 `app/services/json_extract.py`

- `parse_llm_json_array`: 코드펜스 제거, `[`~`]` 구간 추출, `json.loads`, dict만 리스트에 담음.

### 3.18 `app/services/export.py`

- `build_story_text`: 스토리 제목 + 챕터별 `ai_content` 또는 `raw_memory` 연결.
- `to_txt_bytes`, `to_pdf_bytes` (reportlab, 한글 폰트 미등록 시 깨질 수 있음), `to_epub_bytes` (ebooklib + 임시 파일에 epub 작성).

### 3.19 `app/services/__init__.py`, `app/__init__.py`, `app/routers/__init__.py`

- 패키지 마커 (비어 있음).

---

## 4. 프론트엔드 (`frontend/`)

### 4.1 `package.json`

- 의존성: `react`, `react-dom`, `react-router-dom`.
- 스크립트: `dev`, `build`, `lint`, `preview`.

### 4.2 `vite.config.ts`

- 플러그인 `@vitejs/plugin-react`.
- **로컬 개발** `server.proxy`: `/api` → `http://127.0.0.1:8000`.
- **Docker 프로덕션 빌드** 에서는 브라우저가 **같은 오리진**(예: `http://localhost:8080`)으로 `/api` 요청 → **Nginx가 backend로 프록시** (`frontend/nginx.conf`). 별도 `VITE_*` API 베이스 URL 불필요.

### 4.3 `index.html`

- 엔트리 스크립트 `src/main.tsx`, 제목 한글.

### 4.4 `src/main.tsx`

- `ReactDOM.createRoot`로 `App` 마운트, `index.css` 로드.

### 4.5 `src/App.tsx`

- `BrowserRouter`: `/` → `Dashboard`, `/story/:storyId` → `StoryWorkspace`, 나머지 → `/` 리다이렉트.

### 4.6 `src/api.ts`

- `fetch` 기반 `/api` 호출 래퍼 `req<T>`.
- 타입: `Story`, `Episode`, `BibleEntry`.
- `api.stories`, `api.episodes`, `api.bible`, `api.agent` (expand, finalize, bibleExtract/Apply, bridge, rag, consistency, style, export).

### 4.7 `src/pages/Dashboard.tsx`

- 스토리 목록 로드, 제목·장르 입력 후 생성, 링크로 워크스페이스 이동.

### 4.8 `src/pages/StoryWorkspace.tsx`

- 스토리·에피소드·바이블 로드, 챕터 타임라인, 좌측 메모·우측 AI 본문 텍스트 영역.
- 버튼: AI 초안, 저장, 요약·인덱싱, 바이블 자동 반영, RAG 검색, 일관성, 문체, 브리지 모달, TXT/EPUB/PDF 다운로드, 플로팅 바이블 패널.

### 4.9 `src/index.css`, `src/App.css`

- `index.css`: 전역 다크 톤·폼 스타일.
- `App.css`: Vite 초기 템플릿 잔여 파일. **`App.tsx`에서 import하지 않음** (삭제해도 동작에는 영향 없음).

### 4.10 TypeScript 설정

- `tsconfig.json`, `tsconfig.app.json`, `tsconfig.node.json`: 컴파일/경로 설정.

---

## 5. 엔드투엔드 데이터 흐름 (요약)

1. 사용자가 스토리·챕터를 만들고 메모(`raw_memory`)를 저장 (`PATCH` 에피소드).
2. **AI 초안**: `expand-draft`가 DB에서 컨텍스트를 조립해 LLM 호출 → 프론트가 `ai_content`에 반영 후 사용자가 **저장**.
3. **요약·RAG**: `finalize-episode`가 요약을 DB에 쓰고 청크·벡터 인덱싱.
4. **바이블**: `bible-apply`가 같은 에피소드 본문에서 추출해 **새 행만 추가** (기존 항목 수정/머지 없음).
5. **RAG 검색**: 키워드 또는 벡터로 과거 청크·에피소드 스니펫 표시.

---

## 6. 초기 기획 대비 아직 없거나 다른 점

다음은 논의되었으나 **현재 코드에 포함되지 않았거나 수준만 맞춘 부분**입니다.

- **LangChain / LangGraph / CrewAI**: 미연동. 단일 FastAPI 라우트에서 순차 호출.
- **MCP(Model Context Protocol)**: 미구현. DB 접근은 서버 내부 SQLAlchemy로만.
- **Supabase**: 미사용. 로컬/직접 호스팅 PostgreSQL 가정.
- **인증/멀티유저**: 없음.
- **바이블 중복 제거·병합**: 없음 (`bible-apply`는 계속 INSERT).
- **에피소드 삭제 시 임베딩 정리**: 청크는 CASCADE로 삭제되나, 운영 정책은 미문서화.
- **PDF 한글**: reportlab 기본 폰트 한계.

---

## 7. 사용자(본인)가 해야 할 일 체크리스트

### Docker로 전체 실행할 때

1. **Docker / Docker Compose** 설치.
2. 프로젝트 **루트**에 `.env` 생성: `cp .env.example .env` 후 **`GEMINI_API_KEY` 또는 `OPENAI_API_KEY`** 등 입력.
3. **`docker compose up --build -d`**
4. 브라우저에서 **http://localhost:8080** 접속 (백엔드는 컨테이너 부팅 시 Alembic 자동 적용).
5. **API 키 과금·쿼터** 확인.

### 로컬 개발만 할 때

1. **DB**: `docker compose up -d db` 또는 로컬 Postgres+pgvector.
2. **`backend/.env`**: `DATABASE_URL`(예: `localhost:5433`), API 키, `AI_PROVIDER` 등.
3. **`alembic upgrade head`** (로컬 셸에서).
4. **`backend` venv** + `pip install -r requirements.txt` + `uvicorn`.
5. **`frontend`**: `npm install` + `npm run dev` → http://localhost:5173

### 공통·운영

- (선택) **HTTPS**, 커스텀 도메인 시 **`CORS_ALLOW_ORIGINS`** 에 실제 오리진 추가.
- (선택) DB **백업**, 시크릿 저장소 (루트 `.env` 는 git에 올리지 말 것).

---

## 8. AI(코딩 어시스턴트)에게 더 구체적으로 지시하면 좋은 내용

지시에 포함하면 구현이 빨라지는 예시입니다.

- **인증**: “JWT + 로그인 화면, 스토리는 `user_id`로 격리”처럼 방식과 필드를 명시.
- **바이블**: “동일 `name`이면 `description`만 업데이트” 등 **머지 규칙**.
- **LangGraph**: “노드: retrieve → draft → self_check → finalize, 상태 타입은 …”
- **MCP**: “스토리 바이블 조회/추가 툴 스키마와 Postgres 연결 방식”
- **배포**: “클라우드에 compose 그대로”, “Kubernetes로 쪼개기”, “HTTPS Termination을 어디에 둘지” 등.
- **품질**: “일관성 검토 시 N화 전체 본문 포함, 토큰 상한 초과 시 … 요약 체인”
- **UI**: “모바일에서 듀얼 에디터 세로 스택”, “타임라인 가로 드래그” 등 레이아웃.

---

## 9. `requirements.txt`와 동기화하는 방법

```bash
cd backend
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install <새패키지>
pip freeze > requirements.txt
# 선택: 파일 맨 위 주석(생성 안내)을 다시 추가
```

---

## 10. API 경로 빠른 색인 (모두 `/api` 접두사)

- `GET/POST .../stories`, `GET/PATCH/DELETE .../stories/{id}`
- `.../stories/{id}/episodes` (CRUD)
- `.../stories/{id}/bible` (CRUD)
- `POST .../agent/expand-draft`, `finalize-episode/{id}`, `bible-extract`, `bible-apply/{id}`, `bridge`, `rag-search`, `consistency`, `style-transfer`, `export`
- `GET .../agent/context-preview/{story_id}?chapter_num=`
- `GET .../health`

---

문서 버전: 저장소 현재 트리 기준. 코드 변경 시 이 파일의 해당 절을 함께 갱신하는 것을 권장합니다.
