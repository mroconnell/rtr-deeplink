"""add search_tsv (generated tsvector) to meeting_pages -- Search Step 2a

Revision ID: c1d2e3f4a5b6
Revises: bf4f54a11e5f
Create Date: 2026-08-17 21:00:00.000000

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, Sequence[str], None] = "bf4f54a11e5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Postgres full-text search over the materialized search_corpus.

    Postgres-only, entirely: SQLite (local dev / CI) gets nothing from
    this migration and archive/db/models.py deliberately does NOT map the
    column -- crud.list_pages() feature-detects it at runtime
    (crud._fts_available()) and falls back to the LIKE path when it's
    absent, so this migration and the code that uses it can be deployed
    in either order without the UndefinedColumnError incident that
    bf4f54a11e5f's deploy caused (BACKLOG_DONE.md, 2026-08-17).

    A GENERATED ... STORED column, not a plain column + backfill: Postgres
    computes it from search_corpus on every INSERT/UPDATE, so there is no
    ingest-time code path to keep in sync and no one-time backfill script
    to run -- exactly the two seams that bit bf4f54a11e5f. `left(..., 3e6)`
    caps the input so the expression can never exceed tsvector's hard 1MB
    limit and fail a row's INSERT (measured: a 534K-char corpus yields a
    138KB tsvector; prod's largest meeting is ~400K chars; the cap is ~9x
    that). 'english' config: stemming + stopwords for the English-majority
    corpus; the Spanish minority degrades to near-`simple`, not to wrong
    results (see BACKLOG.md's search entry).

    The ADD COLUMN rewrites the table computing to_tsvector for every row
    under an ACCESS EXCLUSIVE lock -- ~30s for prod's 77MB corpus (bench:
    161s for 444MB), during which /m/* reads block. Run at a quiet moment.
    The GIN index is built CONCURRENTLY (no lock) in an autocommit block,
    since CREATE INDEX CONCURRENTLY can't run inside Alembic's default
    transaction.

    ADD COLUMN IF NOT EXISTS, not a plain ADD COLUMN (WO-10 first-deploy
    incident, 2026-08-17): the autocommit_block() below force-commits
    whatever preceded it, so if a run gets this far and then the
    CONCURRENTLY step fails or is interrupted, the column is already
    permanently committed even though Alembic never wrote the version
    stamp -- exactly what happened when this ran by hand that day. A
    retry then re-hit a plain ADD COLUMN and got DuplicateColumnError
    forever, wedging the preDeployCommand this migration's own WO-10 was
    meant to protect. IF NOT EXISTS makes a retry from that half-applied
    state converge instead of repeating the same failure.
    """
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(
        "ALTER TABLE meeting_pages ADD COLUMN IF NOT EXISTS search_tsv tsvector "
        "GENERATED ALWAYS AS "
        "(to_tsvector('english', left(coalesce(search_corpus, ''), 3000000))) STORED"
    )
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_meeting_pages_search_tsv "
            "ON meeting_pages USING gin (search_tsv)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_meeting_pages_search_tsv")
    op.execute("ALTER TABLE meeting_pages DROP COLUMN IF EXISTS search_tsv")
