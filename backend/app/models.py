import enum
import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
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
    style_guide: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str] = mapped_column(String(16), default="KO")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    episodes: Mapped[list["Episode"]] = relationship(
        back_populates="story",
        order_by="Episode.chapter_num",
    )
    bible_entries: Mapped[list["StoryBibleEntry"]] = relationship(back_populates="story")


class Episode(Base):
    """챕터(에피소드). 본문 텍스트는 `episode_bodies` 행들로만 보관한다."""

    __tablename__ = "episodes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    story_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stories.id", ondelete="CASCADE"))
    chapter_num: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_memory: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[EpisodeStatus] = mapped_column(
        Enum(EpisodeStatus, name="episodestatus", values_callable=lambda obj: [e.value for e in obj]),
        default=EpisodeStatus.draft,
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
    link_to_previous: Mapped["BodySegmentLink | None"] = mapped_column(
        Enum(BodySegmentLink, name="bodysegmentlink", values_callable=lambda obj: [e.value for e in obj]),
        nullable=True,
    )

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

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    story_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stories.id", ondelete="CASCADE"))
    episode_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("episodes.id", ondelete="CASCADE"))
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding = mapped_column(Vector(_dim), nullable=True)

    episode: Mapped["Episode"] = relationship(back_populates="chunks")
