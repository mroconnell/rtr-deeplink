"""add chunk_plan to transcription_jobs

Revision ID: b4d9e2a6c7f8
Revises: a3c8f1d5b6e7
Create Date: 2026-08-30 13:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b4d9e2a6c7f8"
down_revision: Union[str, Sequence[str], None] = "a3c8f1d5b6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """WO-79: nullable per-clip chunk plan for a meeting whose adapter
    found more than one real video file that together make up the whole
    meeting, with no single combined recording available (some Swagit
    tenants -- see app/platforms/swagit.py and
    app/platforms/media_probe.py's probe_multi_clip_chunk_plan()). NULL
    for every existing/ordinary single-video job -- no backfill needed,
    the worker only ever reads this for a job created after this column
    exists (see archive/db/models.py's TranscriptionJob.chunk_plan
    docstring)."""
    op.add_column(
        "transcription_jobs",
        sa.Column("chunk_plan", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("transcription_jobs", "chunk_plan")
