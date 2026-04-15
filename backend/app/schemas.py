import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from app.models import BibleCategory, BodySegmentLink, EpisodeStatus


class StoryCreate(BaseModel):
    title: str
    genre: str = ""
    synopsis: str | None = None
    style_guide: str | None = None
    language: str = "KO"


class StoryUpdate(BaseModel):
    title: str | None = None
    genre: str | None = None
    synopsis: str | None = None
    style_guide: str | None = None
    language: str | None = None


class StoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    genre: str
    synopsis: str | None
    style_guide: str | None
    language: str
    created_at: datetime


class EpisodeCreate(BaseModel):
    chapter_num: int
    raw_memory: str | None = None
    ai_content: str | None = None
    summary: str | None = None
    status: EpisodeStatus = EpisodeStatus.draft


class EpisodeUpdate(BaseModel):
    chapter_num: int | None = None
    raw_memory: str | None = None
    summary: str | None = None
    status: EpisodeStatus | None = None


class EpisodeBodyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    segment_index: int
    title: str | None
    content: str
    link_to_previous: BodySegmentLink | None


class EpisodeBodyItemIn(BaseModel):
    """본문 블록 한 덩어리. 배열 순서가 챕터 안 순서. 첫 항목의 link_to_previous는 저장 시 무시됨."""

    title: str | None = None
    content: str = ""
    link_to_previous: BodySegmentLink | None = None


class ReplaceEpisodeBodiesRequest(BaseModel):
    bodies: list[EpisodeBodyItemIn]


class EpisodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    story_id: uuid.UUID
    chapter_num: int
    raw_memory: str | None
    ai_content: str | None
    summary: str | None
    status: EpisodeStatus
    bodies: list[EpisodeBodyOut] = []


class BibleCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    category: BibleCategory
    name: str
    description: str | None = None
    metadata: dict[str, Any] | None = None


class BibleUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    category: BibleCategory | None = None
    name: str | None = None
    description: str | None = None
    metadata: dict[str, Any] | None = None


class BibleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    story_id: uuid.UUID
    category: BibleCategory
    name: str
    description: str | None
    metadata: dict[str, Any] | None = Field(
        default=None,
        validation_alias=AliasChoices("extra", "metadata"),
        serialization_alias="metadata",
    )


class ExpandDraftRequest(BaseModel):
    episode_id: uuid.UUID
    raw_memory: str | None = None
    genre_override: str | None = None


class ExpandDraftResponse(BaseModel):
    ai_content: str
    context_used: dict[str, Any]


class BibleExtractRequest(BaseModel):
    episode_id: uuid.UUID
    ai_content: str


class BibleExtractResponse(BaseModel):
    entries: list[dict[str, Any]]


class BibleCommitRequest(BaseModel):
    """미리보기(extract)로 받은 항목을 DB에 저장할 때 사용. LLM 재호출 없음."""

    entries: list[dict[str, Any]]


class BridgeRequest(BaseModel):
    summary_a: str
    raw_memory_b: str
    story_id: uuid.UUID | None = None
    anchor_excerpt: str | None = Field(default=None, description="직전 본문 끝·직전 블록 등 A 맥락 보강")


class BridgeResponse(BaseModel):
    suggestions: str


class RAGSearchRequest(BaseModel):
    story_id: uuid.UUID
    query: str
    limit: int = 5


class RAGSearchResult(BaseModel):
    source_type: Literal["episode", "bible"] = "episode"
    chunk_id: uuid.UUID | None = None
    bible_entry_id: uuid.UUID | None = None
    episode_id: uuid.UUID | None = None
    chapter_num: int = 0
    snippet: str
    score: float | None = None


class ConsistencyRequest(BaseModel):
    story_id: uuid.UUID
    focus_episode_id: uuid.UUID | None = Field(
        default=None,
        description="해당 챕터 본문만 깊게 검토(다른 화 발췌 제외)",
    )


class ConsistencyResponse(BaseModel):
    report: str


class StyleTransferRequest(BaseModel):
    text: str
    target_style: str


class StyleTransferResponse(BaseModel):
    text: str


class ExportRequest(BaseModel):
    story_id: uuid.UUID
    format: str = "txt"  # txt | pdf | epub
