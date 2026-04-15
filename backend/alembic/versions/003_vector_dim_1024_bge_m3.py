"""임베딩 컬럼을 vector(1024)로 통일 (bge-m3 기본 스택)

Revision ID: 003
Revises: 002
Create Date: 2026-04-08

이미 vector(1536)으로 생성된 DB는 임베딩을 비운 뒤 타입을 바꿉니다.
신규 설치(001이 이미 1024)에서도 실행해도 동일 차원으로 정리됩니다.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE episode_chunks SET embedding = NULL WHERE embedding IS NOT NULL")
    op.execute("UPDATE story_bible SET embedding = NULL WHERE embedding IS NOT NULL")
    op.execute("ALTER TABLE episode_chunks ALTER COLUMN embedding TYPE vector(1024)")
    op.execute("ALTER TABLE story_bible ALTER COLUMN embedding TYPE vector(1024)")


def downgrade() -> None:
    op.execute("UPDATE episode_chunks SET embedding = NULL WHERE embedding IS NOT NULL")
    op.execute("UPDATE story_bible SET embedding = NULL WHERE embedding IS NOT NULL")
    op.execute("ALTER TABLE episode_chunks ALTER COLUMN embedding TYPE vector(1536)")
    op.execute("ALTER TABLE story_bible ALTER COLUMN embedding TYPE vector(1536)")
