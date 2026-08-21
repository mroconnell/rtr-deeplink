"""add best_effort to meeting_pages

Revision ID: d4e5f6a7b8c9
Revises: b7a2c9d4e1f3
Create Date: 2026-08-21 22:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "b7a2c9d4e1f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Persist ResolvedMeeting.best_effort, which the resolver has always
    sent and archive/main.py's IngestRequest silently dropped until now --
    see archive/db/models.py's MeetingPage.best_effort comment for why
    this can't just be inferred from `platform == "unknown"`.

    Deliberately cheap and lock-light: a plain nullable=False column with
    a constant server_default. On Postgres 11+ that's a catalog-only
    change (no table rewrite, no long ACCESS EXCLUSIVE hold), so it's
    safe to run unattended via render.yaml's preDeployCommand on the live
    77MB corpus -- unlike the search_tsv GENERATED column, which really
    did rewrite the table and blocked reads for ~30s.

    No backfill script, and none is possible: `best_effort` is a fact
    about how a resolve was *performed*, not something recomputable from
    the stored row (a fallback result that delegated to YouTube looks
    identical to a native YouTube resolve on this table). Existing rows
    therefore start False and become accurate only as pages are
    re-ingested. That's a real, known limitation, logged in BACKLOG.md
    rather than papered over -- the column is honest going forward, and
    the `platform == "unknown"` and jurisdiction_confidence halves of
    GET /internal/low-trust-pages already cover historical rows from a
    different angle.
    """
    op.add_column(
        "meeting_pages",
        sa.Column(
            "best_effort",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("meeting_pages", "best_effort")
