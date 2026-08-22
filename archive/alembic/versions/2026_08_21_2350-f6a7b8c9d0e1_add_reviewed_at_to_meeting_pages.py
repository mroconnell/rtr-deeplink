"""add reviewed_at to meeting_pages

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-08-21 23:50:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Give GET /internal/low-trust-pages a memory (WO-38).

    That endpoint shipped 2026-08-21 (WO-21) as a stateless JSON dump.
    Its first-ever production call, the same day, returned 474 rows --
    so "re-read it and re-triage everything" is not a workable review
    loop, and the review queue needs somewhere to record that a row has
    been looked at. See archive/db/models.py's MeetingPage.reviewed_at
    comment for why a nullable timestamp rather than a boolean.

    Cheap and lock-light for the same reason as the best_effort
    migration (d4e5f6a7b8c9): a nullable column with no default at all
    is a catalog-only change on Postgres -- no table rewrite, no long
    ACCESS EXCLUSIVE hold -- so it is safe to run unattended via
    render.yaml's preDeployCommand against the live corpus.

    No backfill and no index. Every existing row correctly starts NULL
    ("nobody has reviewed this"), which is the literal truth: no review
    workflow existed before this migration. No index because the only
    query that filters on it (crud.list_low_trust_pages(unreviewed=True))
    already scans the low-trust slice, which is a few hundred rows out
    of ~2200 -- an index would be pure write cost for no measurable read
    gain at this size. Revisit if the archive grows an order of
    magnitude.
    """
    op.add_column(
        "meeting_pages",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("meeting_pages", "reviewed_at")
