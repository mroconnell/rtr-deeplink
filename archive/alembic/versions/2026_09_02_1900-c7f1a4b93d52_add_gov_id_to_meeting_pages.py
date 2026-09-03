"""add gov_id, gov_type and meeting_kind to meeting_pages

The page-level half of `gov_id` -- one namespaced, deterministic
identifier per government, so a government stops being identified by its
name as a string (WO-99, Phase 2 of
rtr-business/research/GOVERNMENT_IDENTITY_ARCHITECTURE.md, §6's
rtr-deeplink block).

Purely additive. Nothing is dropped and nothing is renamed: `jurisdiction`
stays exactly where it is and becomes the display name, `meeting_body`
and `jurisdiction_confidence` are untouched as columns (the latter starts
carrying new *values* -- the resolution tier -- which is what its "plain
string, not an enum" decision already anticipated).

`gov_id` is indexed because it is what `/j/{slug}` groups by and what the
sitemap and every hub query reads; the other two are read alongside a row
that has already been selected and never filtered on.

All three are nullable with no server_default: an un-backfilled row means
"not resolved yet", which is a real and distinguishable state, and
`meeting_kind` NULL specifically means `meeting` (decision D2a) rather
than "unknown" -- writing "meeting" into 5,053 rows to say what the
default already says would be a backfill with no reader.

Revision ID: c7f1a4b93d52
Revises: 1b74c98d2d57
Create Date: 2026-09-02 19:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c7f1a4b93d52"
down_revision: Union[str, Sequence[str], None] = "1b74c98d2d57"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("meeting_pages", sa.Column("gov_id", sa.String(64), nullable=True))
    op.add_column("meeting_pages", sa.Column("gov_type", sa.String(20), nullable=True))
    op.add_column(
        "meeting_pages", sa.Column("meeting_kind", sa.String(20), nullable=True)
    )
    op.create_index("ix_meeting_pages_gov_id", "meeting_pages", ["gov_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_meeting_pages_gov_id", table_name="meeting_pages")
    op.drop_column("meeting_pages", "meeting_kind")
    op.drop_column("meeting_pages", "gov_type")
    op.drop_column("meeting_pages", "gov_id")
