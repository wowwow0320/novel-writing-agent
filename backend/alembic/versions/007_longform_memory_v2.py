"""Long-form memory v2: canonical entities, events, relationships, generation runs.

Revision ID: 007
Revises: 006
Create Date: 2026-05-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBED_DIM = 3072


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_episodes_story_chapter_num",
        "episodes",
        ["story_id", "chapter_num"],
    )
    op.create_index(
        "ix_episode_chunks_story_episode_category",
        "episode_chunks",
        ["story_id", "episode_id", "category"],
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_episode_chunks_content_trgm "
        "ON episode_chunks USING gin (content gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_story_bible_name_trgm "
        "ON story_bible USING gin (name gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_story_bible_description_trgm "
        "ON story_bible USING gin (description gin_trgm_ops)"
    )

    op.create_table(
        "story_entities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("story_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("normalized_name", sa.String(length=256), nullable=False),
        sa.Column("aliases", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("importance", sa.Integer(), nullable=False),
        sa.Column("first_chapter_num", sa.Integer(), nullable=True),
        sa.Column("last_chapter_num", sa.Integer(), nullable=True),
        sa.Column("embedding", Vector(EMBED_DIM), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "story_id",
            "entity_type",
            "normalized_name",
            name="uq_story_entities_story_type_normalized",
        ),
    )
    op.create_index("ix_story_entities_story_type", "story_entities", ["story_id", "entity_type"])
    op.create_index("ix_story_entities_importance", "story_entities", ["story_id", "importance"])
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_story_entities_name_trgm "
        "ON story_entities USING gin (name gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_story_entities_description_trgm "
        "ON story_entities USING gin (description gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_story_entities_embedding_hnsw "
        "ON story_entities USING hnsw ((embedding::halfvec(3072)) halfvec_cosine_ops)"
    )

    op.create_table(
        "story_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("story_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("normalized_title", sa.String(length=512), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("cause", sa.Text(), nullable=True),
        sa.Column("effect", sa.Text(), nullable=True),
        sa.Column("chapter_num", sa.Integer(), nullable=True),
        sa.Column("event_order", sa.Integer(), nullable=True),
        sa.Column("location_entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_episode_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_body_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_chunk_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("importance", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(EMBED_DIM), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["location_entity_id"], ["story_entities.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_body_id"], ["episode_bodies.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_chunk_id"], ["episode_chunks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_episode_id"], ["episodes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_story_events_story_chapter", "story_events", ["story_id", "chapter_num", "event_order"])
    op.create_index("ix_story_events_importance", "story_events", ["story_id", "importance"])
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_story_events_title_trgm "
        "ON story_events USING gin (title gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_story_events_summary_trgm "
        "ON story_events USING gin (summary gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_story_events_embedding_hnsw "
        "ON story_events USING hnsw ((embedding::halfvec(3072)) halfvec_cosine_ops)"
    )

    op.create_table(
        "story_relationships",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("story_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relation_type", sa.String(length=64), nullable=False),
        sa.Column("current_state", sa.String(length=128), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("first_chapter_num", sa.Integer(), nullable=True),
        sa.Column("last_chapter_num", sa.Integer(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["source_entity_id"], ["story_entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_entity_id"], ["story_entities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "story_id",
            "source_entity_id",
            "target_entity_id",
            "relation_type",
            name="uq_story_relationships_canonical_relation",
        ),
    )
    op.create_index("ix_story_relationships_story_relation", "story_relationships", ["story_id", "relation_type"])
    op.create_index("ix_story_relationships_source", "story_relationships", ["source_entity_id"])
    op.create_index("ix_story_relationships_target", "story_relationships", ["target_entity_id"])

    op.create_table(
        "story_relationship_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("story_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relationship_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("episode_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("body_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("paragraph_index", sa.Integer(), nullable=True),
        sa.Column("evidence_excerpt", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("origin_kind", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["body_id"], ["episode_bodies.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["chunk_id"], ["episode_chunks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["episode_id"], ["episodes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["relationship_id"], ["story_relationships.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_story_relationship_evidence_story_episode",
        "story_relationship_evidence",
        ["story_id", "episode_id"],
    )
    op.create_index(
        "ix_story_relationship_evidence_relationship",
        "story_relationship_evidence",
        ["relationship_id"],
    )

    op.create_table(
        "generation_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("story_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("episode_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("run_mode", sa.String(length=64), nullable=False),
        sa.Column("memory_mode", sa.String(length=16), nullable=False),
        sa.Column("segments", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("memory_trace", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("revision_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["episode_id"], ["episodes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_generation_runs_episode_created", "generation_runs", ["episode_id", "created_at"])
    op.create_index("ix_generation_runs_story_created", "generation_runs", ["story_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_generation_runs_story_created", table_name="generation_runs")
    op.drop_index("ix_generation_runs_episode_created", table_name="generation_runs")
    op.drop_table("generation_runs")

    op.drop_index("ix_story_relationship_evidence_relationship", table_name="story_relationship_evidence")
    op.drop_index("ix_story_relationship_evidence_story_episode", table_name="story_relationship_evidence")
    op.drop_table("story_relationship_evidence")

    op.drop_index("ix_story_relationships_target", table_name="story_relationships")
    op.drop_index("ix_story_relationships_source", table_name="story_relationships")
    op.drop_index("ix_story_relationships_story_relation", table_name="story_relationships")
    op.drop_table("story_relationships")

    op.execute("DROP INDEX IF EXISTS ix_story_events_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS ix_story_events_summary_trgm")
    op.execute("DROP INDEX IF EXISTS ix_story_events_title_trgm")
    op.drop_index("ix_story_events_importance", table_name="story_events")
    op.drop_index("ix_story_events_story_chapter", table_name="story_events")
    op.drop_table("story_events")

    op.execute("DROP INDEX IF EXISTS ix_story_entities_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS ix_story_entities_description_trgm")
    op.execute("DROP INDEX IF EXISTS ix_story_entities_name_trgm")
    op.drop_index("ix_story_entities_importance", table_name="story_entities")
    op.drop_index("ix_story_entities_story_type", table_name="story_entities")
    op.drop_table("story_entities")

    op.execute("DROP INDEX IF EXISTS ix_story_bible_description_trgm")
    op.execute("DROP INDEX IF EXISTS ix_story_bible_name_trgm")
    op.execute("DROP INDEX IF EXISTS ix_episode_chunks_content_trgm")
    op.drop_index("ix_episode_chunks_story_episode_category", table_name="episode_chunks")
    op.drop_constraint("uq_episodes_story_chapter_num", "episodes", type_="unique")
