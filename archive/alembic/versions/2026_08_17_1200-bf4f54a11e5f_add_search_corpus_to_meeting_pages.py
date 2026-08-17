"""add search_corpus to meeting_pages

Revision ID: bf4f54a11e5f
Revises: 29d33ef00540
Create Date: 2026-08-17 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "bf4f54a11e5f"
down_revision: Union[str, Sequence[str], None] = "29d33ef00540"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    The GIN trigram index (and the pg_trgm extension it needs) are
    Postgres-only -- dialect-guarded so this migration still runs cleanly
    against a local SQLite dev DB, which just gets the plain column with
    no index. See BACKLOG.md's "Search: move to a materialized/indexed
    column" entry and archive/db/crud.py's list_pages() for how this
    column is populated and queried.
    """
    op.add_column("meeting_pages", sa.Column("search_corpus", sa.Text(), nullable=True))
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        op.create_index(
            "ix_meeting_pages_search_corpus_trgm",
            "meeting_pages",
            ["search_corpus"],
            postgresql_using="gin",
            postgresql_ops={"search_corpus": "gin_trgm_ops"},
        )


def downgrade() -> None:
    """Downgrade schema.

    Deliberately does NOT `DROP EXTENSION pg_trgm` -- a shared extension a
    future feature (or a re-run upgrade) could also depend on, a much
    bigger blast radius than dropping this one column/index.
    """
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_index("ix_meeting_pages_search_corpus_trgm", table_name="meeting_pages")
    op.drop_column("meeting_pages", "search_corpus")
