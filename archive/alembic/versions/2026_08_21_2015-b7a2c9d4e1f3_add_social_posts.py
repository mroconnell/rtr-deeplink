"""add social_posts table

Revision ID: b7a2c9d4e1f3
Revises: 9f3b1c7d4e82
Create Date: 2026-08-21 20:15:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b7a2c9d4e1f3"
down_revision: Union[str, Sequence[str], None] = "9f3b1c7d4e82"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Claim-first dedup ledger for social auto-posting -- see
    archive/db/models.py's SocialPost docstring for the design (the
    unique constraint is what makes posting at-most-once under races).
    Plain, cross-dialect table, same as worker_report_snapshots.
    """
    op.create_table(
        "social_posts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "meeting_page_id",
            sa.Integer(),
            sa.ForeignKey("meeting_pages.id"),
            nullable=False,
        ),
        sa.Column("network", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("post_uri", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("meeting_page_id", "network", name="uq_social_post_target"),
    )
    op.create_index(
        "ix_social_posts_meeting_page_id", "social_posts", ["meeting_page_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_social_posts_meeting_page_id", table_name="social_posts")
    op.drop_table("social_posts")
