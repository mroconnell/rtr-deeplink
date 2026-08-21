"""add worker_report_snapshots table

Revision ID: 9f3b1c7d4e82
Revises: 40645206a333
Create Date: 2026-08-21 16:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9f3b1c7d4e82"
down_revision: Union[str, Sequence[str], None] = "40645206a333"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Single-row snapshot table backing the worker daily activity report
    -- see archive/db/models.py's WorkerReportSnapshot docstring for the
    full design. Plain, cross-dialect table (no dialect-specific index,
    unlike search_tsv/search_vocabulary) -- it's read/written by exactly
    one row's primary key, no scan or fuzzy match ever needed against it.
    """
    op.create_table(
        "worker_report_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cumulative_chunks_completed", sa.Integer(), nullable=False),
        sa.Column("cumulative_jobs_completed", sa.Integer(), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("worker_report_snapshots")
