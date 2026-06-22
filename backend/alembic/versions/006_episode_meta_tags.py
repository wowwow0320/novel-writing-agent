"""Add episodes.meta_tags for chapter-level POV / tense / omnibus / time_jump / allow_discontinuity

Revision ID: 006
Revises: 005
Create Date: 2026-04-20
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "episodes",
        sa.Column("meta_tags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("episodes", "meta_tags")
