from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import agent, episodes, stories, story_bible


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

app.include_router(stories.router, prefix="/api")
app.include_router(episodes.router, prefix="/api")
app.include_router(story_bible.router, prefix="/api")
app.include_router(agent.router, prefix="/api")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
