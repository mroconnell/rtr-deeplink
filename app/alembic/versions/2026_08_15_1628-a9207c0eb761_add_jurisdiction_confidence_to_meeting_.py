"""add jurisdiction_confidence to meeting_resolutions

Revision ID: a9207c0eb761
Revises: ee8f7ff76fb3
Create Date: 2026-08-15 16:28:10.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a9207c0eb761'
down_revision: Union[str, Sequence[str], None] = 'ee8f7ff76fb3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('meeting_resolutions', sa.Column('jurisdiction_confidence', sa.String(length=20), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('meeting_resolutions', 'jurisdiction_confidence')
