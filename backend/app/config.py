from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://novel:novel@localhost:5433/novel_agent"

    ai_provider: Literal["gemini", "openai"] = "openai"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    embedding_provider: Literal["openai", "gemini", "ollama", "none"] = "ollama"
    embedding_dimension: int = 1024
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_embed_model: str = "bge-m3"
    ollama_embed_batch_size: int = 32

    rag_recent_full_episodes: int = 3
    summary_max_chars: int = 300

    # 쉼표 구분. Docker Nginx(8080)·로컬 Vite(5173) 등
    cors_allow_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost,http://127.0.0.1,"
        "http://localhost:8080,http://127.0.0.1:8080"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
