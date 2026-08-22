"""add meeting_page_thumbnails

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-08-21 23:40:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Storage for extracted video-frame meeting cards (WO-28) -- see
    archive/db/models.py's MeetingPageThumbnail docstring for why the
    JPEG bytes live in Postgres rather than behind a new object-storage
    vendor, and why identity is (meeting_page_id, offset_seconds).

    A brand-new table, so this is purely additive: no lock on any
    existing table, no rewrite, nothing to backfill. Rows appear only as
    pages are ingested, rendered, or swept by
    POST /internal/thumbnails/backfill.
    """
    op.create_table(
        "meeting_page_thumbnails",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("meeting_page_id", sa.Integer(), nullable=False),
        sa.Column("offset_seconds", sa.Integer(), nullable=False),
        sa.Column(
            "is_default", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("image_bytes", sa.LargeBinary(), nullable=False),
        sa.Column(
            "content_type",
            sa.String(length=30),
            nullable=False,
            server_default="image/jpeg",
        ),
        sa.Column("etag", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["meeting_page_id"], ["meeting_pages.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "meeting_page_id", "offset_seconds", name="uq_thumbnail_page_offset"
        ),
    )
    op.create_index(
        op.f("ix_meeting_page_thumbnails_meeting_page_id"),
        "meeting_page_thumbnails",
        ["meeting_page_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_meeting_page_thumbnails_meeting_page_id"),
        table_name="meeting_page_thumbnails",
    )
    op.drop_table("meeting_page_thumbnails")
