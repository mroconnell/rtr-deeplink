"""add search_vocabulary table -- Search Step 2b

Revision ID: c684908ce5ff
Revises: c1d2e3f4a5b6
Create Date: 2026-08-18 09:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c684908ce5ff"
down_revision: Union[str, Sequence[str], None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Distinct-word vocabulary table for Search Step 2b's fast fuzzy
    search -- see archive/db/models.py's SearchVocabulary docstring and
    BACKLOG.md's search entry for the full design. Unlike search_tsv
    (c1d2e3f4a5b6), this can't be a generated column: populating it
    needs real application-level tokenization, so it's a plain table,
    cross-dialect like search_corpus (created on SQLite too via
    create_all(), only GIN-trigram indexed -- and only ever queried --
    on Postgres). Brand new and empty either way, so unlike c1d2e3f4a5b6
    this needs no CONCURRENTLY/autocommit dance -- a plain transactional
    CREATE INDEX has nothing to lock.
    """
    op.create_table(
        "search_vocabulary",
        sa.Column("word", sa.String(length=255), primary_key=True),
    )
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Idempotent -- pg_trgm was already created by bf4f54a11e5f, but
        # this migration shouldn't depend on that one having run first.
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        op.create_index(
            "ix_search_vocabulary_word_trgm",
            "search_vocabulary",
            ["word"],
            postgresql_using="gin",
            postgresql_ops={"word": "gin_trgm_ops"},
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_index("ix_search_vocabulary_word_trgm", table_name="search_vocabulary")
    op.drop_table("search_vocabulary")
