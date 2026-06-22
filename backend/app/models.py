import enum
import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import get_settings
from app.database import Base

_dim = get_settings().embedding_dimension


class EpisodeStatus(str, enum.Enum):
    draft = "draft"
    completed = "completed"


class BodySegmentLink(str, enum.Enum):
    """같은 챕터 안에서 이전 본문 블록과 이 블록을 어떻게 이을지 (첫 블록에는 사용하지 않음)."""

    continuous = "continuous"  # 자연스럽게 이어짐
    omnibus = "omnibus"  # 옴니버스·소단편 모음처럼 구분


class BibleCategory(str, enum.Enum):
    char = "CHAR"
    loc = "LOC"
    item = "ITEM"
    event = "EVENT"


class Story(Base):
    __tablename__ = "stories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    genre: Mapped[str] = mapped_column(String(128), default="")
    synopsis: Mapped[str | None] = mapped_column(Text, nullable=True)
    world_setting: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="세계관·대전제 배경(인물 관계, 세계관, 핵심 갈등 등)",
    )
    global_rules: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    style_guide: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str] = mapped_column(String(16), default="KO")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    work_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="챕터 요약들을 모아 압축한 작품 전체 메타 요약",
    )

    episodes: Mapped[list["Episode"]] = relationship(
        back_populates="story",
        order_by="Episode.chapter_num",
    )
    bible_entries: Mapped[list["StoryBibleEntry"]] = relationship(back_populates="story")


class Episode(Base):
    """챕터(에피소드). 본문 텍스트는 `episode_bodies` 행들로만 보관한다."""

    __tablename__ = "episodes"
    __table_args__ = (
        UniqueConstraint("story_id", "chapter_num", name="uq_episodes_story_chapter_num"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    story_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stories.id", ondelete="CASCADE"))
    chapter_num: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_memory: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    chapter_events: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[EpisodeStatus] = mapped_column(
        Enum(EpisodeStatus, name="episodestatus", values_callable=lambda obj: [e.value for e in obj]),
        default=EpisodeStatus.draft,
    )
    meta_tags: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        doc="챕터 레벨 검수 태그 — pov/tense/omnibus/time_jump/allow_discontinuity 등",
    )

    story: Mapped["Story"] = relationship(back_populates="episodes")
    chunks: Mapped[list["EpisodeChunk"]] = relationship(back_populates="episode", cascade="all, delete-orphan")
    bodies: Mapped[list["EpisodeBody"]] = relationship(
        back_populates="episode",
        order_by="EpisodeBody.segment_index",
        cascade="all, delete-orphan",
    )

    @property
    def ai_content(self) -> str | None:
        """API·프론트 호환용 합본 본문(저장 컬럼 아님). bodies는 미리 로드하는 것이 안전하다."""
        from app.services.episode_text import combine_episode_bodies

        if not self.bodies:
            return None
        t = combine_episode_bodies(self.bodies).strip()
        return t or None


class EpisodeBody(Base):
    __tablename__ = "episode_bodies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    story_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stories.id", ondelete="CASCADE"))
    episode_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("episodes.id", ondelete="CASCADE"))
    segment_index: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="블록(세그먼트) 단위 요약 — 챕터 요약의 입력 레이어",
    )
    link_to_previous: Mapped["BodySegmentLink | None"] = mapped_column(
        Enum(BodySegmentLink, name="bodysegmentlink", values_callable=lambda obj: [e.value for e in obj]),
        nullable=True,
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("episode_bodies.id", ondelete="SET NULL"),
        nullable=True,
    )
    meta_tags: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    episode: Mapped["Episode"] = relationship(back_populates="bodies")


class StoryBibleEntry(Base):
    __tablename__ = "story_bible"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    story_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stories.id", ondelete="CASCADE"))
    category: Mapped[BibleCategory] = mapped_column(
        Enum(BibleCategory, name="biblecategory", values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)
    embedding = mapped_column(Vector(_dim), nullable=True)

    story: Mapped["Story"] = relationship(back_populates="bible_entries")


class EpisodeChunk(Base):
    __tablename__ = "episode_chunks"
    __table_args__ = (
        Index("ix_episode_chunks_story_episode_category", "story_id", "episode_id", "category"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    story_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stories.id", ondelete="CASCADE"))
    episode_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("episodes.id", ondelete="CASCADE"))
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        doc="인물/상황/사건 등 검색·컬러링용 분류",
    )
    chunk_meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    embedding = mapped_column(Vector(_dim), nullable=True)

    episode: Mapped["Episode"] = relationship(back_populates="chunks")


class StoryEntity(Base):
    """장편 기억의 canonical 엔티티 원본.

    StoryBibleEntry 는 사용자가 보는 설정 노트로 유지하고, 생성/RAG/Neo4j 동기화는
    이 테이블의 정규화된 엔티티를 기준으로 한다.
    """

    __tablename__ = "story_entities"
    __table_args__ = (
        UniqueConstraint(
            "story_id",
            "entity_type",
            "normalized_name",
            name="uq_story_entities_story_type_normalized",
        ),
        Index("ix_story_entities_story_type", "story_id", "entity_type"),
        Index("ix_story_entities_importance", "story_id", "importance"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    story_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stories.id", ondelete="CASCADE"))
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(256), nullable=False)
    aliases: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    importance: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    first_chapter_num: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_chapter_num: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding = mapped_column(Vector(_dim), nullable=True)
    extra: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class StoryEvent(Base):
    """작품 전체 타임라인에서 질의 가능한 사건 원본."""

    __tablename__ = "story_events"
    __table_args__ = (
        Index("ix_story_events_story_chapter", "story_id", "chapter_num", "event_order"),
        Index("ix_story_events_importance", "story_id", "importance"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    story_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stories.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    normalized_title: Mapped[str] = mapped_column(String(512), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    effect: Mapped[str | None] = mapped_column(Text, nullable=True)
    chapter_num: Mapped[int | None] = mapped_column(Integer, nullable=True)
    event_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    location_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("story_entities.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_episode_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("episodes.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_body_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("episode_bodies.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("episode_chunks.id", ondelete="SET NULL"),
        nullable=True,
    )
    importance: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    embedding = mapped_column(Vector(_dim), nullable=True)
    extra: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class StoryRelationship(Base):
    """canonical 엔티티 간 현재 관계와 최신 상태."""

    __tablename__ = "story_relationships"
    __table_args__ = (
        UniqueConstraint(
            "story_id",
            "source_entity_id",
            "target_entity_id",
            "relation_type",
            name="uq_story_relationships_canonical_relation",
        ),
        Index("ix_story_relationships_story_relation", "story_id", "relation_type"),
        Index("ix_story_relationships_source", "source_entity_id"),
        Index("ix_story_relationships_target", "target_entity_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    story_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stories.id", ondelete="CASCADE"))
    source_entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("story_entities.id", ondelete="CASCADE"),
    )
    target_entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("story_entities.id", ondelete="CASCADE"),
    )
    relation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    current_state: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    first_chapter_num: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_chapter_num: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extra: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class StoryRelationshipEvidence(Base):
    """관계 판단의 원문 근거. 관계 자체를 덮어쓰지 않고 증거를 누적한다."""

    __tablename__ = "story_relationship_evidence"
    __table_args__ = (
        Index("ix_story_relationship_evidence_story_episode", "story_id", "episode_id"),
        Index("ix_story_relationship_evidence_relationship", "relationship_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    story_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stories.id", ondelete="CASCADE"))
    relationship_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("story_relationships.id", ondelete="CASCADE"),
    )
    episode_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("episodes.id", ondelete="SET NULL"),
        nullable=True,
    )
    body_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("episode_bodies.id", ondelete="SET NULL"),
        nullable=True,
    )
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("episode_chunks.id", ondelete="SET NULL"),
        nullable=True,
    )
    paragraph_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    origin_kind: Mapped[str] = mapped_column(String(64), nullable=False, default="episode")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GenerationRun(Base):
    """생성 1회에 사용된 자동 기억 검색·세그먼트·수정 결과 기록."""

    __tablename__ = "generation_runs"
    __table_args__ = (
        Index("ix_generation_runs_episode_created", "episode_id", "created_at"),
        Index("ix_generation_runs_story_created", "story_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    story_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stories.id", ondelete="CASCADE"))
    episode_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("episodes.id", ondelete="SET NULL"),
        nullable=True,
    )
    run_mode: Mapped[str] = mapped_column(String(64), nullable=False, default="expand")
    memory_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="auto")
    segments: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    memory_trace: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    revision_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="completed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StorySummaryNode(Base):
    """Story-RAPTOR 요약 트리의 검색 가능한 기억 노드."""

    __tablename__ = "story_summary_nodes"
    __table_args__ = (
        UniqueConstraint("story_id", "node_key", name="uq_story_summary_nodes_story_node_key"),
        Index(
            "ix_story_summary_nodes_story_level_range",
            "story_id",
            "level",
            "chapter_start",
            "chapter_end",
        ),
        Index("ix_story_summary_nodes_story_stale", "story_id", "stale"),
        Index("ix_story_summary_nodes_parent", "parent_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    story_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stories.id", ondelete="CASCADE"))
    episode_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("episodes.id", ondelete="CASCADE"),
        nullable=True,
    )
    node_key: Mapped[str] = mapped_column(String(256), nullable=False)
    level: Mapped[str] = mapped_column(String(32), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("story_summary_nodes.id", ondelete="SET NULL"),
        nullable=True,
    )
    root_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("story_summary_nodes.id", ondelete="SET NULL"),
        nullable=True,
    )
    depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    path: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    ordinal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chapter_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chapter_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_body_ids: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    source_episode_ids: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    entity_ids: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    event_ids: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    relationship_ids: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    keywords: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    embedding = mapped_column(Vector(_dim), nullable=True)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    coverage_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    extra: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
