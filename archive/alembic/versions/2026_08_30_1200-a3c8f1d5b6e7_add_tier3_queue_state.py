"""add tier3_queue_state table

Revision ID: a3c8f1d5b6e7
Revises: 1864f9d7702e
Create Date: 2026-08-30 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a3c8f1d5b6e7"
down_revision: Union[str, Sequence[str], None] = "1864f9d7702e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Single-row snapshot of tier-3 queue depth -- see
    archive/db/models.py's Tier3QueueState docstring for the full design.
    Same shape as worker_report_snapshots: no dialect-specific index,
    read/written by exactly one row's primary key.
    """
    op.create_table(
        "tier3_queue_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("remaining", sa.Integer(), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("tier3_queue_state")
