"""add packet_link to meeting_pages

Revision ID: 1b74c98d2d57
Revises: 1e6107751720
Create Date: 2026-08-31 17:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "1b74c98d2d57"
down_revision: Union[str, Sequence[str], None] = "1e6107751720"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("meeting_pages", sa.Column("packet_link", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("meeting_pages", "packet_link")
