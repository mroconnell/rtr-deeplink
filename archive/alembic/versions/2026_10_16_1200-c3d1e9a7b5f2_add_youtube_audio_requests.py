"""add youtube_audio_requests table

Revision ID: c3d1e9a7b5f2
Revises: 1816f75c1098
Create Date: 2026-10-16 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c3d1e9a7b5f2"
down_revision: Union[str, Sequence[str], None] = "1816f75c1098"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """WO-1969: readers' "Request Transcript from Audio" presses on
    YouTube-hosted meetings, one row per video. See archive/db/models.py's
    YoutubeAudioRequest docstring. A brand-new table: no existing code
    reads it until this deploy, so the order of deploy and migration does
    not matter.
    """
    op.create_table(
        "youtube_audio_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("video_id", sa.String(length=16), nullable=False),
        sa.Column(
            "meeting_page_id",
            sa.Integer(),
            sa.ForeignKey("meeting_pages.id"),
            nullable=True,
        ),
        sa.Column("url_normalized", sa.String(length=2048), nullable=True),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.Column(
            "first_requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        op.f("ix_youtube_audio_requests_video_id"),
        "youtube_audio_requests",
        ["video_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_youtube_audio_requests_meeting_page_id"),
        "youtube_audio_requests",
        ["meeting_page_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_youtube_audio_requests_meeting_page_id"),
        table_name="youtube_audio_requests",
    )
    op.drop_index(
        op.f("ix_youtube_audio_requests_video_id"),
        table_name="youtube_audio_requests",
    )
    op.drop_table("youtube_audio_requests")
