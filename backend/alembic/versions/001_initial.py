"""단일 초기 스키마 — 챕터(episode) 본문은 episode_bodies에만 저장

Revision ID: 001
Revises:
Create Date: 2026-04-08

기존 002·003 체인을 폐기하고 한 번에 생성합니다.
로컬/도커 DB는 볼륨 삭제 후 `alembic upgrade head` 로 맞추세요.
임베딩 차원은 .env 의 EMBEDDING_DIMENSION 과 일치해야 합니다 (기본 1024, Ollama bge-m3).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 기본 스택: Ollama bge-m3 (1024). OpenAI 임베딩도 dimensions=1024로 맞춤.
EMBED_DIM = 1024


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "stories",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("genre", sa.String(length=128), nullable=True),
        sa.Column("synopsis", sa.Text(), nullable=True),
        sa.Column("style_guide", sa.Text(), nullable=True),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "episodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("story_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chapter_num", sa.Integer(), nullable=False),
        sa.Column("raw_memory", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("draft", "completed", name="episodestatus"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "episode_bodies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("story_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("episode_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("segment_index", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "link_to_previous",
            sa.Enum("continuous", "omnibus", name="bodysegmentlink"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["episode_id"], ["episodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_episode_bodies_episode_segment", "episode_bodies", ["episode_id", "segment_index"])
    op.create_table(
        "story_bible",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("story_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "category",
            sa.Enum("CHAR", "LOC", "ITEM", "EVENT", name="biblecategory"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("embedding", Vector(EMBED_DIM), nullable=True),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "episode_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("story_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("episode_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(EMBED_DIM), nullable=True),
        sa.ForeignKeyConstraint(["episode_id"], ["episodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("episode_chunks")
    op.drop_table("story_bible")
    op.drop_index("ix_episode_bodies_episode_segment", table_name="episode_bodies")
    op.drop_table("episode_bodies")
    op.drop_table("episodes")
    op.drop_table("stories")
    op.execute("DROP TYPE IF EXISTS bodysegmentlink")
    op.execute("DROP TYPE IF EXISTS biblecategory")
    op.execute("DROP TYPE IF EXISTS episodestatus")
