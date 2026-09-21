"""add context_entries table

Revision ID: ab513927d28d
Revises: e2a1c7b45d93
Create Date: 2026-09-21 09:00:00.000000

WO-942: the public `/context` feed -- short, editor-written entries that
cite a social-media post showing a clip from a public meeting and deep-link
into this Archive's own `/m/{slug}?t=`. See
`archive/db/models.py`'s `ContextEntry` docstring for the full design
(including why it's unrelated to the existing `social_posts` table) and
`archive/utils/context_links.py`/`archive/utils/context_editors.py` for
the parsing and editor-allowlist code that writes and reads these rows.

Empty on arrival, and harmless while empty: no existing code path reads
or writes `context_entries` before this feature's own routes/crud
functions ship, and `archive/db/crud.py`'s `_context_available()` already
tolerates the table not existing yet (same deploy-order-tolerance pattern
as `_thumbnails_available()`), so this migration and that code are safe
to land in either order.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "ab513927d28d"
down_revision: Union[str, Sequence[str], None] = "e2a1c7b45d93"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "context_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("social_url", sa.String(length=2048), nullable=False),
        sa.Column("social_url_key", sa.String(length=512), nullable=False),
        sa.Column("network", sa.String(length=20), nullable=False),
        sa.Column("source_label", sa.String(length=120), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "meeting_page_id",
            sa.Integer(),
            sa.ForeignKey("meeting_pages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("t_seconds", sa.Integer(), nullable=True),
        sa.Column("match_kind", sa.String(length=20), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("created_by_clerk_user_id", sa.String(length=64), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("social_url_key", name="uq_context_entry_social_url_key"),
    )
    op.create_index(
        "ix_context_entries_meeting_page_id", "context_entries", ["meeting_page_id"]
    )
    op.create_index(
        "ix_context_entries_created_by_clerk_user_id",
        "context_entries",
        ["created_by_clerk_user_id"],
    )
    # The public feed's own read pattern -- "published rows, newest first"
    # -- so that query hits one composite index instead of a full scan.
    op.create_index(
        "ix_context_entries_status_published_at",
        "context_entries",
        ["status", "published_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_context_entries_status_published_at", table_name="context_entries"
    )
    op.drop_index(
        "ix_context_entries_created_by_clerk_user_id", table_name="context_entries"
    )
    op.drop_index("ix_context_entries_meeting_page_id", table_name="context_entries")
    op.drop_table("context_entries")
