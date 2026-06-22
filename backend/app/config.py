from typing import Any, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://novel:novel@localhost:5433/novel_agent"

    ai_provider: Literal["gemini", "openai"] = "openai"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_embed_model: str = "text-embedding-3-large"
    openai_bible_model: str = "gpt-5-nano"

    embedding_provider: Literal["openai", "gemini", "ollama", "none"] = "openai"
    embedding_dimension: int = 3072
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_embed_model: str = "bge-m3"
    ollama_embed_batch_size: int = 32

    rag_recent_full_episodes: int = 3
    summary_max_chars: int = 300
    hierarchy_block_summary_max_chars: int = 220
    hierarchy_chapter_summary_max_chars: int = 420
    work_summary_max_chars: int = 1200
    graph_enabled: bool = False
    neo4j_http_url: str = "http://127.0.0.1:7474"
    neo4j_username: str = "neo4j"
    neo4j_password: str = ""
    neo4j_database: str = "neo4j"
    graph_conflict_policy: Literal["postgres", "graph", "manual"] = "graph"

    scene_stitch_mode: Literal["rule", "llm"] = "rule"
    scene_plan_max_scenes: int = 6
    expand_orchestrator_max_segments: int = 8
    expand_accumulated_prev_max_chars: int = 14000
    memo_qa_max_questions: int = 10
    memo_qa_max_freeform_chars: int = 2000

    # 쉼표 구분. Docker Nginx(8080)·로컬 Vite(5173) 등
    cors_allow_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost,http://127.0.0.1,"
        "http://localhost:8080,http://127.0.0.1:8080"
    )

    @field_validator(
        "neo4j_password",
        "openai_api_key",
        "gemini_api_key",
        mode="before",
    )
    @classmethod
    def strip_optional_outer_quotes(cls, v: Any) -> Any:
        """`.env` 에서 NEO4J_PASSWORD=\"...\" 처럼 감싼 경우 값에 따옴표가 들어가 Neo4j 인증이 실패하는 것을 방지."""
        if v is None or not isinstance(v, str):
            return v
        s = v.strip()
        if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
            return s[1:-1].strip()
        return s


def get_settings() -> Settings:
    # 매 호출 시 환경을 읽어 .env 변경이 다음 요청부터 반영되도록 함(개발 편의).
    return Settings()
