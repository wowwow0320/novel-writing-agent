"""UPDATE_PLAN: world_setting/global_rules, episode body meta, chunk category/meta

Revision ID: 005
Revises: 004
Create Date: 2026-04-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("stories", sa.Column("world_setting", sa.Text(), nullable=True))
    op.add_column(
        "stories",
        sa.Column("global_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "episode_bodies",
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "episode_bodies",
        sa.Column("meta_tags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_foreign_key(
        "fk_episode_bodies_parent_id",
        "episode_bodies",
        "episode_bodies",
        ["parent_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("episode_chunks", sa.Column("category", sa.String(length=32), nullable=True))
    op.add_column(
        "episode_chunks",
        sa.Column("chunk_meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("episode_chunks", "chunk_meta")
    op.drop_column("episode_chunks", "category")
    op.drop_constraint("fk_episode_bodies_parent_id", "episode_bodies", type_="foreignkey")
    op.drop_column("episode_bodies", "meta_tags")
    op.drop_column("episode_bodies", "parent_id")
    op.drop_column("stories", "global_rules")
    op.drop_column("stories", "world_setting")
