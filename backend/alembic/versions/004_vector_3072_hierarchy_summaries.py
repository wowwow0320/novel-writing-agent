"""벡터 3072 + 계층 요약 컬럼 (블록 요약 → 챕터 사건/요약 → 작품 전체 요약)

Revision ID: 004
Revises: 003
Create Date: 2026-04-15

- pgvector 컬럼을 vector(3072)로 변경 (기존 임베딩은 NULL 처리 후 타입 변경).
- episode_bodies.body_summary: 블록(세그먼트) 단위 요약.
- episodes.chapter_events: 챕터 단위 추출 사건(JSON 배열).
- stories.work_summary: 챕터 요약을 모은 작품 전체 메타 요약.

.env 의 EMBEDDING_DIMENSION=3072 과 맞추세요.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE episode_chunks SET embedding = NULL WHERE embedding IS NOT NULL")
    op.execute("UPDATE story_bible SET embedding = NULL WHERE embedding IS NOT NULL")
    op.execute("ALTER TABLE episode_chunks ALTER COLUMN embedding TYPE vector(3072)")
    op.execute("ALTER TABLE story_bible ALTER COLUMN embedding TYPE vector(3072)")

    op.add_column("episode_bodies", sa.Column("body_summary", sa.Text(), nullable=True))
    op.add_column("episodes", sa.Column("chapter_events", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("stories", sa.Column("work_summary", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("stories", "work_summary")
    op.drop_column("episodes", "chapter_events")
    op.drop_column("episode_bodies", "body_summary")

    op.execute("UPDATE episode_chunks SET embedding = NULL WHERE embedding IS NOT NULL")
    op.execute("UPDATE story_bible SET embedding = NULL WHERE embedding IS NOT NULL")
    op.execute("ALTER TABLE episode_chunks ALTER COLUMN embedding TYPE vector(1024)")
    op.execute("ALTER TABLE story_bible ALTER COLUMN embedding TYPE vector(1024)")
