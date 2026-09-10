"""add jurisdiction_raw to meeting_pages

Revision ID: b120d92c3f45
Revises: d8b2c5e07a41
Create Date: 2026-09-10 09:00:00.000000

Gov-id audit, 2026-09-10. `meeting_pages.jurisdiction` is the DISPLAY
name and, from this change on, is generated from the registry row for
every page that has a real `gov_id` (pinned, registry, unverified and
inferred tiers -- previously only the first two). That is what makes a
minted government's meeting page agree with its own hub ("Housing
Authority of the County of Santa Clara, CA" on both, rather than "County
of Santa Clara, CA / Housing Authority" on the page). The string the
adapter actually extracted was the only evidence a reviewer had for an
`inferred` row -- its id came from its tenant's neighbours, not from
its own name -- so it moves to its own column rather than being lost.

Nullable, no backfill: rows archived before this column existed keep
NULL, which is the honest "we never kept it" rather than a reconstruction.
Text, not String(200): it is the adapter's raw output and is not
bounded by anything this schema controls.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b120d92c3f45"
down_revision: Union[str, Sequence[str], None] = "d8b2c5e07a41"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "meeting_pages", sa.Column("jurisdiction_raw", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("meeting_pages", "jurisdiction_raw")
