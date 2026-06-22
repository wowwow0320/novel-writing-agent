"""Story-RAPTOR summary nodes.

Revision ID: 008
Revises: 007
Create Date: 2026-05-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBED_DIM = 3072


def upgrade() -> None:
    op.create_table(
        "story_summary_nodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("story_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("episode_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("node_key", sa.String(length=256), nullable=False),
        sa.Column("level", sa.String(length=32), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("root_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("depth", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("path", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ordinal", sa.Integer(), nullable=True),
        sa.Column("chapter_start", sa.Integer(), nullable=True),
        sa.Column("chapter_end", sa.Integer(), nullable=True),
        sa.Column("source_body_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("source_episode_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("entity_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("event_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("relationship_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("keywords", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("embedding", Vector(EMBED_DIM), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("coverage_score", sa.Float(), nullable=True),
        sa.Column("stale", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["episode_id"], ["episodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_id"], ["story_summary_nodes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["root_id"], ["story_summary_nodes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("story_id", "node_key", name="uq_story_summary_nodes_story_node_key"),
    )
    op.create_index(
        "ix_story_summary_nodes_story_level_range",
        "story_summary_nodes",
        ["story_id", "level", "chapter_start", "chapter_end"],
    )
    op.create_index(
        "ix_story_summary_nodes_story_stale",
        "story_summary_nodes",
        ["story_id", "stale"],
    )
    op.create_index("ix_story_summary_nodes_parent", "story_summary_nodes", ["parent_id"])
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_story_summary_nodes_summary_trgm "
        "ON story_summary_nodes USING gin (summary gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_story_summary_nodes_embedding_hnsw "
        "ON story_summary_nodes USING hnsw ((embedding::halfvec(3072)) halfvec_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_story_summary_nodes_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS ix_story_summary_nodes_summary_trgm")
    op.drop_index("ix_story_summary_nodes_parent", table_name="story_summary_nodes")
    op.drop_index("ix_story_summary_nodes_story_stale", table_name="story_summary_nodes")
    op.drop_index("ix_story_summary_nodes_story_level_range", table_name="story_summary_nodes")
    op.drop_table("story_summary_nodes")
