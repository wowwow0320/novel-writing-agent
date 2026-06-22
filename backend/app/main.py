from contextlib import asynccontextmanager
import logging
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import agent, client_logs, episodes, stories, story_bible

logger = logging.getLogger("uvicorn.error")


def _cors_origins() -> list[str]:
    raw = get_settings().cors_allow_origins
    return [x.strip() for x in raw.split(",") if x.strip()]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield


app = FastAPI(title="Novel Writing Agent API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_api_requests(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - started) * 1000
    path = request.url.path
    if path != "/api/client-log":
        logger.info(
            "[api] %s %s -> %s %.1fms",
            request.method,
            path,
            response.status_code,
            elapsed_ms,
        )
    return response

app.include_router(stories.router, prefix="/api")
app.include_router(episodes.router, prefix="/api")
app.include_router(story_bible.router, prefix="/api")
app.include_router(agent.router, prefix="/api")
app.include_router(client_logs.router, prefix="/api")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
