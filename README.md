# 소설 집필 AI 에이전트 (Novel Writing Agent)

React 프론트엔드 + FastAPI 백엔드 + PostgreSQL(pgvector)로 장편 소설 집필을 지원하는 웹 애플리케이션입니다.

## 전체 파일·폴더 구조

```
novel-writing-agent/
├── README.md
├── PROJECT_REFERENCE.md
├── .env.example                 # Docker Compose용 (루트). 복사 → .env
├── .gitignore
├── docker-compose.yml           # db + backend + frontend
│
├── backend/
│   ├── Dockerfile               # Python 3.12, uvicorn
│   ├── docker-entrypoint.sh     # DB 대기 → alembic upgrade → uvicorn
│   ├── .dockerignore
│   ├── requirements.txt
│   ├── .env.example             # 로컬 uvicorn 개발용
│   ├── alembic.ini
│   ├── alembic/
│   │   ├── env.py               # ALEMBIC_SYNC_URL 환경변수 지원
│   │   ├── script.py.mako
│   │   └── versions/001_initial.py
│   └── app/
│       ├── main.py              # CORS: CORS_ALLOW_ORIGINS (쉼표 구분)
│       ├── config.py
│       └── … (routers, services 등)
│
└── frontend/
    ├── Dockerfile               # Node 빌드 + nginx 정적 서빙
    ├── nginx.conf               # /api → backend:8000 프록시
    ├── .dockerignore
    ├── package.json
    ├── vite.config.ts           # 로컬 개발 시 /api 프록시
    ├── public/
    └── src/
        └── …
```

**버전 관리에서 제외**: `backend/.venv/`, `backend/.env`, **루트 `.env`**, `frontend/node_modules/`, `frontend/dist/`

---

## Docker로 전체 실행 (권장 흐름)

한 번에 **PostgreSQL · API · 웹 UI** 가 올라갑니다.

1. **프로젝트 루트**에 환경 파일 준비  
   ```bash
   cp .env.example .env
   ```  
   `.env` 에 `GEMINI_API_KEY` 또는 `OPENAI_API_KEY` 등을 입력합니다.  
   (Compose가 이 파일을 읽어 `backend` 컨테이너 환경변수로 넘깁니다.)

2. **빌드 및 기동**  
   ```bash
   docker compose up --build -d
   ```

3. **접속**  
   | 서비스 | URL |
   |--------|-----|
   | **웹 (Nginx + React 빌드)** | http://localhost:8080 |
   | **API 직접 호출** | http://localhost:8000/api/... |
   | **Postgres (호스트 도구용)** | `localhost:5433` (user/pass/db: `novel` / `novel` / `novel_agent`) |

4. **백엔드 컨테이너**는 시작 시 `db` 가 준비될 때까지 대기한 뒤 **`alembic upgrade head`** 를 실행하고 `uvicorn` 을 띄웁니다.

5. **중지**  
   ```bash
   docker compose down
   ```

---

## 로컬 개발 (Docker 없이 또는 DB만 Docker)

| 구분 | 설명 |
|------|------|
| **Python venv** | `backend` 에서 `python3 -m venv .venv` 후 `pip install -r requirements.txt` |
| **DB만 Docker** | `docker compose up -d db` 후 `DATABASE_URL` 을 `localhost:5433` 으로 맞춤 |
| **Node** | `frontend` 에서 `npm install` / `npm run dev` → http://localhost:5173 (Vite가 `/api` → 127.0.0.1:8000 프록시) |

**로컬 백엔드**  
```bash
cd backend
cp .env.example .env   # DATABASE_URL·API 키 수정
source .venv/bin/activate
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**로컬 프론트**  
```bash
cd frontend
npm install
npm run dev
```

---

## 런타임·도구 정리

| 구분 | 역할 |
|------|------|
| **Docker Compose** | **db + backend + frontend** 3서비스. 프로덕션에 가까운 일체 실행. |
| **Python venv** | 로컬·CI에서 백엔드 개발 시. **Anaconda는 포함하지 않음** (원하면 conda 안에서 동일 `pip install -r requirements.txt` 가능). |
| **Node/npm** | 프론트 빌드·로컬 HMR. Docker 프론트는 이미지 안에서 `npm run build` 후 nginx만 실행. |

상세 로직·API·CORS·Alembic은 **`PROJECT_REFERENCE.md`** 를 참고하세요.

---

## `requirements.txt` 갱신

로컬 venv에서:

```bash
cd backend
source .venv/bin/activate
pip install <패키지>
pip freeze > requirements.txt
```

Docker 백엔드 이미지는 **`backend/requirements.txt`** 를 사용합니다. (이미지는 **Python 3.12** 기준)

---

## 문서

- **`PROJECT_REFERENCE.md`**: 파일별 역할, Docker 구성, API, 남은 작업, AI 지시 팁.
