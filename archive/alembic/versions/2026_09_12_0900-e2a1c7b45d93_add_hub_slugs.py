"""add hub_slugs table

Revision ID: e2a1c7b45d93
Revises: aaf88dc886a4
Create Date: 2026-09-12 09:00:00.000000

WO-256, from `docs/investigations/hub_architecture_audit.md` §4: one
stored, eventually-frozen `/j/{slug}` per government, so a rename, an
override or a backfill can change which government a page belongs to
without moving a reader's URL. See `archive/db/models.py`'s `HubSlug`
docstring for the design and the gate, and `archive/db/hub_slugs.py`
for the read/write path.

Empty on arrival, and harmless while empty: `crud._hub_identity()` falls
back to exactly today's live computation for every government with no
row, so this migration and the code that reads it are safe to deploy in
either order. `scripts/freeze_hub_slugs.py --apply` is the one-time
backfill that populates it from exactly today's computed slug, which is
why day one changes zero live URLs.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e2a1c7b45d93"
down_revision: Union[str, Sequence[str], None] = "aaf88dc886a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "hub_slugs",
        sa.Column("gov_id", sa.String(length=320), primary_key=True),
        sa.Column("hub_slug", sa.String(length=255), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=True),
    )
    # "Whose hub is this slug?" is the reader-path question, so the slug
    # is indexed; it is deliberately NOT unique (two real governments can
    # legitimately share a display name -- see the model's own comment).
    op.create_index("ix_hub_slugs_hub_slug", "hub_slugs", ["hub_slug"])


def downgrade() -> None:
    op.drop_index("ix_hub_slugs_hub_slug", table_name="hub_slugs")
    op.drop_table("hub_slugs")
