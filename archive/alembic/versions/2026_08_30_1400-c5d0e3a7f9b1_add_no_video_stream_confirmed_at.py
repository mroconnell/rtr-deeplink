"""add no_video_stream_confirmed_at to meeting_pages

Revision ID: c5d0e3a7f9b1
Revises: b4d9e2a6c7f8
Create Date: 2026-08-30 14:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c5d0e3a7f9b1"
down_revision: Union[str, Sequence[str], None] = "b4d9e2a6c7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """WO-85: give the meeting-card backfill sweep a permanent memory of
    "this page's video is audio-only, don't retry it."

    BACKLOG_DONE.md's 2026-08-30 "19 audio-only meetings can never have a
    card" entry found these pages fail thumbnail extraction on every
    single sweep, forever: extract_and_store()'s existing cooldown
    (_failed_at) is in-memory and per-process, so it resets on every
    deploy and re-attempts (and re-fails) the same doomed ffmpeg call.
    See archive/db/models.py's MeetingPage.no_video_stream_confirmed_at
    comment for the full reasoning.

    Same cheap, lock-light shape as reviewed_at's migration (f6a7b8c9d0e1)
    and best_effort's (d4e5f6a7b8c9): a nullable column with no default
    at all is a catalog-only change on Postgres -- no table rewrite, no
    long ACCESS EXCLUSIVE hold -- safe to run unattended via render.yaml's
    preDeployCommand against the live corpus.

    No backfill and no index. Every existing row correctly starts NULL
    ("never probed") -- nothing has retroactively confirmed any existing
    page audio-only, that only happens going forward as
    extract_and_store() runs. No index: the only query that filters on it
    (list_pages_missing_default_thumbnail()) already scans a small slice
    of the corpus (pages missing a default thumbnail), not the whole
    table.
    """
    op.add_column(
        "meeting_pages",
        sa.Column(
            "no_video_stream_confirmed_at", sa.DateTime(timezone=True), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column("meeting_pages", "no_video_stream_confirmed_at")
