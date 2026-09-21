"""add title to context_entries

Revision ID: f3a29d6e1c48
Revises: ab513927d28d
Create Date: 2026-09-21 15:00:00.000000

WO-945: an optional short editor-written title/headline on a `/context`
feed entry (`archive/db/models.py`'s `ContextEntry.title`). Nullable, no
backfill -- every entry written before this column existed simply has no
title, which is the honest state rather than a reconstruction.

Deploy-order tolerance (CLAUDE.md's "never reference a new column in code
the same deploy it's added unless the code tolerates its absence"): this
column is nullable with no server-side default requirement, so the only
window this creates -- old app code running against the new schema, in
the gap between this migration running (render.yaml's preDeployCommand)
and the new build actually serving -- is harmless. Old code simply never
reads or writes `title`, and a NULL column with nothing writing to it is
indistinguishable from the column not existing yet as far as that code is
concerned. No feature-detect needed, unlike context_entries' own arrival
in WO-943 (see `archive/db/crud.py`'s `_context_available()`), because
this is a column on an already-migration-gated table, not a whole new
table a pre-migration deploy might query directly.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f3a29d6e1c48"
down_revision: Union[str, Sequence[str], None] = "ab513927d28d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "context_entries", sa.Column("title", sa.String(length=160), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("context_entries", "title")
