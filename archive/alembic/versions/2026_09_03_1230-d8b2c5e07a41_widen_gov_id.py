"""widen meeting_pages.gov_id from 64 to 320 characters

WO-101. The 64 in WO-99's migration was asserted, not derived, and its
own comment said so confidently: "64 characters is generous for every
namespace above; the longest real id in the 2026-09-02 scoring run is a
minted slug well under that." The scoring run's own `minted.csv`
contained two ids of 66 characters at the time that was written.

It failed in production, on the real backfill, part-way through:

    asyncpg.exceptions.StringDataRightTruncationError:
      value too long for type character varying(64)
    [parameters: (..., 'rtr:us:ca:los-angeles-county-metropolitan-
      transportation-authority', 'county', 355)]

333 of 5,053 pages had been written. Nothing was corrupted -- the
script commits per row, so the failing row rolled back alone and every
earlier row is consistent -- and a re-run resumes, because it skips
rows already current. That property is the only reason this is an
inconvenience rather than an incident.

**The width is derived this time.** Two id shapes have a length that
depends on data rather than on a fixed code:

  rtr:<cc>:<st>:<slug>   the slug comes from `MeetingPage.jurisdiction`,
                         which is String(200), so this is <= 10 + 200 = 210
  rtr:unknown:<host>     a hostname, which DNS caps at 253 octets,
                         so this is <= 12 + 253 = 265

320 covers both with room. The longest id the archive actually produces
today is 66, and the longest tenant host is 47 -- but "what the data
happens to contain" is precisely the reasoning that failed here, so the
bound is taken from what the schema and DNS permit instead.

The other two columns from that migration were checked the same way and
are genuinely bounded: `gov_type` and `meeting_kind` are closed
vocabularies whose longest members are "special_district" (16) and
"press_conference" (16), both well inside String(20).

Widening a varchar is a catalog-only change in Postgres (no table
rewrite, no index rebuild), so this is fast on any table size. The
downgrade narrows back to 64 and will fail if any row already holds a
longer id -- which is the honest behaviour: those rows cannot be
represented in the old column.

Revision ID: d8b2c5e07a41
Revises: c7f1a4b93d52
Create Date: 2026-09-03 12:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d8b2c5e07a41"
down_revision: Union[str, Sequence[str], None] = "c7f1a4b93d52"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # batch_alter_table for SQLite, which has no ALTER COLUMN and is the
    # local/test path CI builds from migrations.
    with op.batch_alter_table("meeting_pages") as batch_op:
        batch_op.alter_column(
            "gov_id",
            existing_type=sa.String(64),
            type_=sa.String(320),
            existing_nullable=True,
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("meeting_pages") as batch_op:
        batch_op.alter_column(
            "gov_id",
            existing_type=sa.String(320),
            type_=sa.String(64),
            existing_nullable=True,
        )
