"""add agenda_versions

Revision ID: 059f7f323f16
Revises: 1816f75c1098
Create Date: 2026-10-16 22:53:32.042198

WO-1966: one row per distinct agenda or packet text per meeting page,
deduplicated by content hash. A new table only: nothing existing changes,
and the code that writes it catches every error, so either deploy order
is safe.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "059f7f323f16"
down_revision: Union[str, Sequence[str], None] = "1816f75c1098"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "agenda_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("meeting_page_id", sa.Integer(), nullable=False),
        sa.Column("doc_role", sa.String(length=20), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("format", sa.String(length=40), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("resolved_url", sa.Text(), nullable=True),
        sa.Column("extractor", sa.String(length=40), nullable=False),
        sa.Column("extractor_version", sa.Integer(), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "last_checked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["meeting_page_id"], ["meeting_pages.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "meeting_page_id",
            "doc_role",
            "content_hash",
            name="uq_agenda_version_page_role_hash",
        ),
    )
    op.create_index(
        op.f("ix_agenda_versions_meeting_page_id"),
        "agenda_versions",
        ["meeting_page_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_agenda_versions_meeting_page_id"), table_name="agenda_versions"
    )
    op.drop_table("agenda_versions")
