"""add immutable Context candidate editor reviews

Revision ID: 1816f75c1098
Revises: 9f20cd299f30
Create Date: 2026-09-23 08:23:54.694365

WO-1014: additive review history, with no modification of imported evidence
or public entries. Deploy with Archive before the resolver.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "1816f75c1098"
down_revision: Union[str, Sequence[str], None] = "9f20cd299f30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "context_candidate_revisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("candidate_id", sa.Integer(), nullable=False),
        sa.Column("candidate_version", sa.Integer(), nullable=False),
        sa.Column("source_observation_id", sa.Integer(), nullable=False),
        sa.Column("fields", sa.JSON(), nullable=False),
        sa.Column("clerk_user_id", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"], ["context_candidates.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "candidate_id", "candidate_version", name="uq_candidate_revision_version"
        ),
    )
    op.create_index(
        op.f("ix_context_candidate_revisions_candidate_id"),
        "context_candidate_revisions",
        ["candidate_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_context_candidate_revisions_candidate_id"),
        table_name="context_candidate_revisions",
    )
    op.drop_table("context_candidate_revisions")
