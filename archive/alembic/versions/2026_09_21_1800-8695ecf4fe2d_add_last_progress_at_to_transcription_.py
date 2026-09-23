"""add last_progress_at to transcription_jobs

Revision ID: 8695ecf4fe2d
Revises: f3a29d6e1c48
Create Date: 2026-09-21 18:00:00.000000

WO-936: the stuck-job detector's own timestamp. worker/main.py's claim
heartbeat refreshes `claimed_at` every 60s independently of real
progress (WO-57), so `claimed_at`/`updated_at` alone can never tell a
genuinely wedged or OOM-looping job apart from a healthy one -- both
were previously invisible to every existing check (BACKLOG.md's OOM and
claim-heartbeat entries). `last_progress_at` is written only inside
crud.report_chunk_result(), on both success and failure, so it moves
only on real activity.

Nullable, no full backfill: a page archived before this migration keeps
NULL until its next report_chunk_result() call, and
crud.list_stuck_transcription_jobs() coalesces with created_at when
reading it.

One narrow backfill IS done here, deliberately: any row currently in an
active status (queued/in_progress/retry_scheduled) gets
last_progress_at = updated_at, so a job genuinely still progressing at
deploy time isn't immediately misread as stalled since its creation.
Bounded by MAX_CONCURRENT_TRANSCRIPTION_JOBS (15) in practice, not a
scan of the whole table.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8695ecf4fe2d"
down_revision: Union[str, Sequence[str], None] = "f3a29d6e1c48"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "transcription_jobs",
        sa.Column("last_progress_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """
        UPDATE transcription_jobs
        SET last_progress_at = updated_at
        WHERE status IN ('queued', 'in_progress', 'retry_scheduled')
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("transcription_jobs", "last_progress_at")
