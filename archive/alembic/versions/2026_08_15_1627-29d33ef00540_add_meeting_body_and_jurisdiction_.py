"""add meeting_body and jurisdiction_confidence to meeting_pages

Revision ID: 29d33ef00540
Revises: a6556277a68d
Create Date: 2026-08-15 16:27:45.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '29d33ef00540'
down_revision: Union[str, Sequence[str], None] = 'a6556277a68d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('meeting_pages', sa.Column('meeting_body', sa.Text(), nullable=True))
    op.add_column('meeting_pages', sa.Column('jurisdiction_confidence', sa.String(length=20), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('meeting_pages', 'jurisdiction_confidence')
    op.drop_column('meeting_pages', 'meeting_body')
