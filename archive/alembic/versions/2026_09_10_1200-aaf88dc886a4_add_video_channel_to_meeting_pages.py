"""add video_channel and video_channel_id to meeting_pages

Revision ID: aaf88dc886a4
Revises: b120d92c3f45
Create Date: 2026-09-10 12:00:00.000000

Gov-id audit, 2026-09-10. The account that published a page's video on a
shared host -- a YouTube channel handle ("@TownofWoodside") or a Vimeo
owner slug -- plus YouTube's permanent channel id. The identifying detail
for a bare YouTube/Vimeo paste is never in the address, and the adapter
had it on every resolve and dropped it; storing it on the page (rather
than checking it in passing) is what lets a channel rule added LATER
reach pages already archived through the ordinary backfill, without
re-fetching them. Passed to the resolver as a `page_hint` so a
`tenant_overrides.csv` row with `match=channel=@Handle` can fire --
635 YouTube and 17 Vimeo such rows were learned from the archive's own
pages in reports/shared_host_study_2026-09-09/ and waited on exactly this.

Nullable, no backfill: pages archived before this ran keep NULL until
their next resolve. Text: handles and slugs are short, but neither is
bounded by anything this schema controls.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "aaf88dc886a4"
down_revision: Union[str, Sequence[str], None] = "b120d92c3f45"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("meeting_pages", sa.Column("video_channel", sa.Text(), nullable=True))
    op.add_column(
        "meeting_pages", sa.Column("video_channel_id", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("meeting_pages", "video_channel_id")
    op.drop_column("meeting_pages", "video_channel")
