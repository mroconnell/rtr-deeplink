"""add saved_items

Revision ID: 34f94d49a2ac
Revises: 76a4a2820a2b
Create Date: 2026-08-10 13:46:58.373504

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '34f94d49a2ac'
down_revision: Union[str, Sequence[str], None] = '76a4a2820a2b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'saved_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('clerk_user_id', sa.String(length=64), nullable=False),
        sa.Column('item_type', sa.String(length=20), nullable=False),
        sa.Column('meeting_page_id', sa.Integer(), nullable=True),
        sa.Column('search_params', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['meeting_page_id'], ['meeting_pages.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_saved_items_clerk_user_id'), 'saved_items', ['clerk_user_id'], unique=False)
    op.create_index(op.f('ix_saved_items_item_type'), 'saved_items', ['item_type'], unique=False)
    op.create_index(op.f('ix_saved_items_meeting_page_id'), 'saved_items', ['meeting_page_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_saved_items_meeting_page_id'), table_name='saved_items')
    op.drop_index(op.f('ix_saved_items_item_type'), table_name='saved_items')
    op.drop_index(op.f('ix_saved_items_clerk_user_id'), table_name='saved_items')
    op.drop_table('saved_items')
