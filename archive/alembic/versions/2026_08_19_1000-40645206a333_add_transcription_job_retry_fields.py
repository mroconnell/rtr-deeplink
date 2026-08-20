"""add transcription_job retry/failure-history fields

Revision ID: 40645206a333
Revises: c684908ce5ff
Create Date: 2026-08-19 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "40645206a333"
down_revision: Union[str, Sequence[str], None] = "c684908ce5ff"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Backs the escalating-backoff retry for a real user-priority
    TranscriptionJob that's exhausted MAX_CONSECUTIVE_CHUNK_FAILURES (see
    archive/db/crud.py's report_chunk_result()/MAX_JOB_RETRIES and
    models.py's TranscriptionJob docstring) plus richer per-chunk failure
    diagnostics -- both added 2026-08-19 after a real job (Redwood City,
    CA) failed silently with no operator notification and no way to tell
    *why* beyond a single overwritten "ffmpeg extraction failed" string.
    """
    op.add_column(
        "transcription_jobs",
        sa.Column(
            "failure_history",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
    )
    op.add_column(
        "transcription_jobs",
        sa.Column(
            "retry_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "transcription_jobs",
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("transcription_jobs", "next_retry_at")
    op.drop_column("transcription_jobs", "retry_count")
    op.drop_column("transcription_jobs", "failure_history")
